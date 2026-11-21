"""POST /v1/chat/completions. OpenAI-compatible proxy used by the ElevenLabs agent. Checks LLM_PROXY_SECRET, reads call_id from dynamic variables, streams Lightning, records turns, emits transcript events.

Correction verified in #6 (docs/ELEVENLABS.md): `call_id` and the secret arrive inside `elevenlabs_extra_body`
in the request body (what the voice adapter passed as `custom_llm_extra_body` when it started the call),
not in dynamic variables. The `Authorization: Bearer` header is accepted for the same secret as a fallback.

Transcript events wait for app.events (#9); first-token latency goes to a hook on app.state until
metrics.py (#10) merges. Both are wired in this router once those land.
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
from sqlmodel import func, select

from app.config import MissingSetting, Settings
from app.db import session_scope
from app.models import Call, Task, Turn
from app.nemotron.call_agent import (
    ChatStream,
    LightningClient,
    build_messages,
    collect,
    relay,
)
from app.nemotron.call_prompt import CallSpec

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


def last_clinic_line(messages: list[dict]) -> str | None:
    for m in reversed(messages):
        if m.get("role") == "user":
            text = (m.get("content") or "").strip()
            return text or None
        if m.get("role") == "assistant":
            return None
    return None


def record_turn(engine: Engine, call_id: str, speaker: str, text: str) -> Turn | None:
    """Append one turn unless this speaker's last stored line is the same (ElevenLabs resends the whole conversation each turn and retries on slow replies)."""
    if not text:
        return None
    with session_scope(engine) as session:
        last = session.exec(
            select(Turn).where(Turn.call_id == call_id, Turn.speaker == speaker).order_by(Turn.seq.desc())
        ).first()
        if last is not None and last.text == text:
            return None
        count = session.exec(select(func.count()).select_from(Turn).where(Turn.call_id == call_id)).one()
        turn = Turn(call_id=call_id, seq=int(count) + 1, speaker=speaker, text=text)
        session.add(turn)
        session.flush()
        session.refresh(turn)
        session.expunge(turn)
        return turn


def record_first_token(request: Request, call_id: str, seconds: float) -> None:
    """First-token latency for the Nemotron metrics. Collected on app.state until metrics.py (#10) merges."""
    log.info("call_agent first token call_id=%s seconds=%.3f", call_id, seconds)
    sink = getattr(request.app.state, "first_token_latencies", None)
    if isinstance(sink, list):
        sink.append({"call_id": call_id, "seconds": round(seconds, 4), "at": time.time()})


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
    record_turn(engine, call_id, "clinic", last_clinic_line(incoming) or "")
    messages = build_messages(spec, incoming)  # elevenlabs_extra_body and the vendor system prompt never go upstream
    client = lightning_client(request)

    def on_first_token(seconds: float) -> None:
        record_first_token(request, call_id, seconds)

    def on_complete(text: str) -> None:
        record_turn(engine, call_id, "agent", text)

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
