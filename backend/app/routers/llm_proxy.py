"""POST /v1/chat/completions. OpenAI-compatible proxy used by the ElevenLabs agent. Checks LLM_PROXY_SECRET, reads call_id from dynamic variables, streams Lightning, records turns, emits transcript events.

Correction verified in #6 (docs/ELEVENLABS.md): `call_id` and the secret arrive inside `elevenlabs_extra_body`
in the request body (what the voice adapter passed as `custom_llm_extra_body` when it started the call),
not in dynamic variables. The `Authorization: Bearer` header is accepted for the same secret as a fallback.

Turns are keyed by their position in the conversation ElevenLabs sends, so a retried request maps onto the same
rows and a genuine repeated line later in the call is kept. A turn and its `transcript` event are written in one
transaction behind a unique (call_id, seq), so overlapping retries write exactly one of each. Transcript events
have `contact` visibility (docs/ARCHITECTURE.md: visible to both roles; the open item in docs/DECISIONS.md covers
screening clinic lines).
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
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import metrics
from app.config import MissingSetting, Settings
from app.db import session_scope
from app.events import EventBus
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


def record_turn(engine: Engine, bus: EventBus, spec: CallSpec, seq: int, speaker: str, text: str, *, simulated: bool = False) -> Turn | None:
    """Write turn `seq` of this call and its transcript event in ONE transaction, or nothing.

    `turns (call_id, seq)` is unique, so of two overlapping retries exactly one INSERT succeeds and carries the event
    row with it; the other hits the constraint, rolls back and writes nothing (invariant 7). The bus is told after
    commit. A retry whose Lightning wording differs keeps the stored line.

    Live calls reach this from the proxy; mock and simulator calls reach it from `Pipeline._voice_event` with
    `simulated=True` (#87), so both kinds of call leave the same rows and the same event, labelled honestly."""
    if not text:
        return None
    payload = {"call_id": spec.call_id, "seq": seq, "speaker": speaker, "text": text}
    if simulated:
        payload["simulated"] = True
    turn = Turn(call_id=spec.call_id, seq=seq, speaker=speaker, text=text)
    event = Event(
        task_id=spec.task_id,
        type="transcript",
        payload_json=json.dumps(payload, ensure_ascii=False),
        visibility="contact",  # docs/ARCHITECTURE.md: transcripts are visible to both roles; see the D6 open item
    )
    try:
        with session_scope(engine) as session:
            session.add(turn)
            session.add(event)
            session.flush()
            session.refresh(turn)
            session.refresh(event)
            session.expunge(turn)
            session.expunge(event)
    except IntegrityError:
        log.info("turn %s of call %s already recorded; retry ignored", seq, spec.call_id)
        return None
    bus.publish(event, _owner_id(engine, spec.task_id))
    return turn


def recorded_turn(engine: Engine, call_id: str, seq: int) -> Turn | None:
    """The turn already written for this position of the call, or None when the position is new."""
    with session_scope(engine) as session:
        turn = session.exec(select(Turn).where(Turn.call_id == call_id, Turn.seq == seq)).first()
        if turn is not None:
            session.expunge(turn)
        return turn


def replay_response(text: str, call_id: str, seq: int, *, stream: bool):
    """The recorded line in the OpenAI shape ElevenLabs asked for: one content chunk then a stop chunk and [DONE], or
    the chat.completion object. No upstream call, no metrics row: nothing was generated."""
    created = int(time.time())
    completion_id = f"chatcmpl-replay-{call_id}-{seq}"
    if not stream:
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": "lifeline-replay",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }
        )
    chunks = [
        {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "lifeline-replay",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
        {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": "lifeline-replay",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    payload = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return StreamingResponse(iter([payload.encode()]), media_type="text/event-stream", headers=SSE_HEADERS)


def _owner_id(engine: Engine, task_id: str) -> str:
    with session_scope(engine) as session:
        task = session.get(Task, task_id)
        return task.owner_id if task else ""


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
    recorded = recorded_turn(engine, call_id, agent_seq)
    if recorded is not None:
        # ElevenLabs re-sent a conversation whose agent position is settled (a retry, or a re-ask after the receptionist
        # spoke over the agent). Speak what the record says, so speech and transcript agree, and never pay Lightning twice (#90).
        log.info("replaying recorded turn %s of call %s; Lightning not called", agent_seq, call_id)
        return replay_response(recorded.text, call_id, agent_seq, stream=bool(body.get("stream", True)))
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
    # Non-streaming fallback: Lightning is a blocking HTTP call, so it runs on a worker thread like the webhook work.
    text, last = await run_in_threadpool(lambda: collect(client.stream_chat(messages)))
    on_first_token(time.perf_counter() - started)
    await run_in_threadpool(on_complete, text)
    return JSONResponse(
        {
            "id": (last or {}).get("id", f"chatcmpl-{call_id}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": (last or {}).get("model", "nemotron-lightning"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        }
    )
