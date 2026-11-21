"""POST /v1/chat/completions. OpenAI-compatible proxy used by the ElevenLabs agent. Checks LLM_PROXY_SECRET, reads call_id from dynamic variables, streams Lightning, records turns, emits transcript events.

Correction verified in #6 (docs/ELEVENLABS.md): `call_id` and the secret arrive inside `elevenlabs_extra_body`
in the request body (what the voice adapter passed as `custom_llm_extra_body` when it started the call),
not in dynamic variables. The `Authorization: Bearer` header is accepted for the same secret as a fallback.

Turns are keyed by their position in the conversation ElevenLabs sends, so a retried request maps onto the same
rows and a genuine repeated line later in the call is kept. Every turn has one `transcript` event with `contact`
visibility (docs/ARCHITECTURE.md: transcripts are visible to both roles); a retry repairs a missing event.
First-token latency is one `call_agent` row in metrics.jsonl per proxy turn.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine
from sqlmodel import select

from app import metrics
from app.config import MissingSetting, Settings
from app.db import session_scope
from app.events import EventBus, emit
from app.models import Call, Event, Task, Turn
from app.nemotron.call_agent import (
    ChatStream,
    LightningClient,
    build_messages,
    collect,
    relay,
)
from app.nemotron.types import CallSpec

log = logging.getLogger("lifeline.llm_proxy")
router = APIRouter(tags=["llm-proxy"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def extra_body(body: dict) -> dict:
    extra = body.get("elevenlabs_extra_body")
    return extra if isinstance(extra, dict) else {}


def check_secret(request: Request, body: dict, settings: Settings) -> None:
    expected = settings.llm_proxy_secret
    if not expected:
        raise HTTPException(503, "LLM_PROXY_SECRET is not set in .env")
    provided = extra_body(body).get("proxy_secret")
    if not isinstance(provided, str):
        auth = request.headers.get("authorization", "")
        provided = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(401, "bad or missing proxy secret")


def extract_call_id(body: dict) -> str:
    call_id = extra_body(body).get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise HTTPException(400, "elevenlabs_extra_body.call_id is missing; the voice adapter must pass custom_llm_extra_body")
    return call_id


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)  # Python 3.11+ accepts a trailing Z


def load_spec(engine: Engine, call_id: str) -> CallSpec:
    """The redacted facts for this call, from the calls and tasks rows the orchestrator wrote."""
    with session_scope(engine) as session:
        call = session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, f"unknown call_id {call_id!r}; only calls LifeLine started may use the proxy")
        task = session.get(Task, call.task_id)
        if task is None:
            raise HTTPException(404, f"call {call_id!r} has no task")
        intake = json.loads(task.intake_json or "{}")
        windows_raw = json.loads(task.windows_json or "[]")
        return CallSpec(
            call_id=call.id,
            task_id=task.id,
            clinic_name=call.clinic_name,
            care_type=intake.get("care_type") or "appointment",
            budget_max=intake.get("budget_max"),
            insurance_carrier=intake.get("insurance_carrier"),
            windows=[(_parse_dt(w["start"]), _parse_dt(w["end"])) for w in windows_raw],
        )


def conversation_turns(messages: list[dict]) -> tuple[list[dict], int | None, int]:
    """The non-system messages in order, the clinic's line position (when the last message is the clinic's), and the
    position the agent's reply will take. Positions are 1-based indexes into the conversation ElevenLabs sends, so
    a retried request maps to the same turns and a genuine repeat later in the call gets a new position."""
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    n = len(turns)
    clinic_seq = n if n and turns[-1].get("role") == "user" and (turns[-1].get("content") or "").strip() else None
    return turns, clinic_seq, n + 1


def record_turn(engine: Engine, bus: EventBus, spec: CallSpec, seq: int, speaker: str, text: str) -> Turn | None:
    """Make sure turn `seq` of this call and its transcript event both exist. A retry that finds the turn keeps the
    stored line (even if Lightning now words it differently) and only repairs a missing event (invariant 7)."""
    if not text:
        return None
    call_id = spec.call_id
    with session_scope(engine) as session:
        turn = session.exec(select(Turn).where(Turn.call_id == call_id, Turn.seq == seq)).first()
        if turn is None:
            turn = Turn(call_id=call_id, seq=seq, speaker=speaker, text=text)
            session.add(turn)
            session.flush()
        session.refresh(turn)
        session.expunge(turn)
        has_event = any(
            json.loads(e.payload_json).get("call_id") == call_id and json.loads(e.payload_json).get("seq") == seq
            for e in session.exec(select(Event).where(Event.task_id == spec.task_id, Event.type == "transcript")).all()
        )
    if not has_event:
        emit(engine, bus, spec.task_id, "transcript",
             {"call_id": call_id, "seq": seq, "speaker": turn.speaker, "text": turn.text}, visibility="contact")
    return turn


def record_first_token(request: Request, call_id: str, seconds: float) -> None:
    """First-token latency for the Nemotron metrics: one call_agent row in metrics.jsonl, numbers only."""
    settings: Settings = request.app.state.settings
    client = getattr(request.app.state, "lightning_client", None)
    model = getattr(client, "model_id", None) or settings.nemotron_lightning_id or "unknown"
    first_token_ms = round(seconds * 1000)
    log.info("call_agent first token call_id=%s first_token_ms=%d", call_id, first_token_ms)
    try:
        metrics.record_first_token(model=model, call_id=call_id, first_token_ms=first_token_ms)
    except OSError as exc:  # a metrics file that cannot be written must never break a live call
        log.warning("could not write metrics row: %s", exc)


def lightning_client(request: Request) -> ChatStream:
    client = getattr(request.app.state, "lightning_client", None)
    if client is None:
        settings: Settings = request.app.state.settings
        try:
            client = LightningClient(api_key=settings.nvidia_api_key or "", model_id=settings.require_model("lightning"))
        except (MissingSetting, ValueError) as exc:
            raise HTTPException(503, str(exc)) from exc
        request.app.state.lightning_client = client
    return client


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "body must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    settings: Settings = request.app.state.settings
    engine: Engine = request.app.state.engine
    check_secret(request, body, settings)
    call_id = extract_call_id(body)
    spec = load_spec(engine, call_id)
    incoming = body.get("messages") if isinstance(body.get("messages"), list) else []
    bus: EventBus = request.app.state.bus
    turns, clinic_seq, agent_seq = conversation_turns(incoming)
    if clinic_seq is not None:
        record_turn(engine, bus, spec, clinic_seq, "clinic", (turns[-1].get("content") or "").strip())
    messages = build_messages(spec, incoming)  # elevenlabs_extra_body and the vendor system prompt never go upstream
    client = lightning_client(request)

    def on_first_token(seconds: float) -> None:
        record_first_token(request, call_id, seconds)

    def on_complete(text: str) -> None:
        record_turn(engine, bus, spec, agent_seq, "agent", text)

    if body.get("stream", True):
        chunks: Iterator[dict] = client.stream_chat(messages)
        return StreamingResponse(
            relay(chunks, on_first_token=on_first_token, on_complete=on_complete),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    started = time.perf_counter()
    text, last = collect(client.stream_chat(messages))
    on_first_token(time.perf_counter() - started)
    on_complete(text)
    return JSONResponse(
        {
            "id": (last or {}).get("id", f"chatcmpl-{call_id}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": (last or {}).get("model", "nemotron-lightning"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        }
    )
