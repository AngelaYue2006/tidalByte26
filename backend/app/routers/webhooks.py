"""POST /api/webhooks/twilio/sms (signature, allowlist, YES or contact reply) and POST /api/webhooks/elevenlabs/post-call (transcript + data collection -> call_result).

Only the ElevenLabs post-call handler is here (#21). Twilio SMS belongs to #22 and #23.
Order of checks: signature (ElevenLabs-Signature, HMAC-SHA256 over "<t>.<raw body>", 30-minute window),
then the event type, then the call it belongs to (conversation_id -> calls.external_ref, falling back to the
dynamic variable call_id), then the per-call idempotency check inside call_results. The reply is 200 as soon
as the payload is accepted; the work runs as a background task so ElevenLabs never retries a slow handler.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import Engine
from sqlmodel import select

from app import call_results
from app.config import MissingSetting, Settings
from app.db import session_scope
from app.events import EventBus
from app.models import Call, Task
from app.nemotron.ranker import ChatJSON, NvidiaChatClient

log = logging.getLogger("lifeline.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

SIGNATURE_HEADER = "elevenlabs-signature"
SIGNATURE_TOLERANCE_S = 30 * 60
HANDLED_TYPES = ("post_call_transcription", "call_initiation_failure")


def verify_signature(raw_body: bytes, header: str | None, secret: str, *, now: float | None = None) -> None:
    """Same scheme as the vendor SDK's construct_event: `t=<unix secs>,v0=<hex hmac-sha256(secret, "<t>.<body>")>`."""
    if not header:
        raise HTTPException(401, "missing ElevenLabs-Signature header")
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    timestamp, signature = parts.get("t"), parts.get("v0")
    if not timestamp or not signature:
        raise HTTPException(401, "signature header lacks t= or v0=")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "signature timestamp is not an integer") from exc
    if sent_at < (now if now is not None else time.time()) - SIGNATURE_TOLERANCE_S:
        raise HTTPException(401, "signature timestamp outside the 30-minute window")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise HTTPException(401, "signature does not match")


def sign(raw_body: bytes, secret: str, *, at: int | None = None) -> str:
    """The header value for a body: used by tests and by the mock voice adapter when it posts to this endpoint."""
    t = at if at is not None else int(time.time())
    return f"t={t},v0=" + hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()


def find_call(engine: Engine, conversation_id: str | None, dynamic_call_id: str | None) -> tuple[Call, Task] | None:
    with session_scope(engine) as session:
        call = None
        if conversation_id:
            call = session.exec(select(Call).where(Call.external_ref == conversation_id)).first()
        if call is None and dynamic_call_id:
            call = session.get(Call, dynamic_call_id)
            if call is not None and conversation_id and not call.external_ref:
                call.external_ref = conversation_id
                session.add(call)
                session.flush()
        if call is None:
            return None
        task = session.get(Task, call.task_id)
        if task is None:
            return None
        session.refresh(call)
        session.expunge(call)
        session.expunge(task)
        return call, task


def super_client(request: Request) -> ChatJSON | None:
    client = getattr(request.app.state, "super_client", None)
    if client is not None:
        return client
    settings: Settings = request.app.state.settings
    try:
        client = NvidiaChatClient(api_key=settings.nvidia_api_key or "", model_id=settings.require_model("super"))
    except (MissingSetting, ValueError) as exc:
        log.warning("Super unavailable for transcript extraction: %s", exc)
        return None
    request.app.state.super_client = client
    return client


def transcript_lines(data: dict) -> list[dict]:
    out = []
    for item in data.get("transcript") or []:
        if not isinstance(item, dict):
            continue
        text = (item.get("message") or "").strip()
        if text:
            out.append({"speaker": "agent" if item.get("role") == "agent" else "clinic", "text": text})
    return out


def process_post_call(engine: Engine, bus: EventBus, settings: Settings, payload: dict, client: ChatJSON | None) -> dict:
    data = payload.get("data") or {}
    conversation_id = data.get("conversation_id")
    dynamic = ((data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {})
    found = find_call(engine, conversation_id, dynamic.get("call_id"))
    if found is None:
        log.warning("post-call webhook for unknown conversation %r; ignored", conversation_id)
        return {"ok": False, "ignored": "unknown_conversation"}
    call, task = found
    if payload.get("type") == "call_initiation_failure":
        return call_results.record_call_failure(engine, bus, call, task, str(data.get("failure_reason") or "unknown"))
    collection = (data.get("analysis") or {}).get("data_collection_results") or {}
    stamp = payload.get("event_timestamp")
    call_date = datetime.fromtimestamp(int(stamp), UTC) if isinstance(stamp, int | float) else datetime.now(UTC)
    return call_results.record_call_result(
        engine, bus, call, task, collection, transcript_lines(data),
        call_date=call_date, timezone=settings.app_timezone, super_client=client,
    )


@router.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request, background: BackgroundTasks) -> dict:
    settings: Settings = request.app.state.settings
    raw = await request.body()
    secret = settings.elevenlabs_webhook_secret
    if secret:
        verify_signature(raw, request.headers.get(SIGNATURE_HEADER), secret)
    elif settings.is_development:
        log.warning("ELEVENLABS_WEBHOOK_SECRET is unset; accepting an unsigned post-call webhook in development")
    else:
        raise HTTPException(503, "ELEVENLABS_WEBHOOK_SECRET is not set")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "body must be JSON") from exc
    if not isinstance(payload, dict) or payload.get("type") not in HANDLED_TYPES:
        return {"ok": True, "ignored": "unhandled_type"}
    client = super_client(request) if payload.get("type") == "post_call_transcription" else None
    background.add_task(process_post_call, request.app.state.engine, request.app.state.bus, settings, payload, client)
    return {"ok": True, "accepted": payload["type"]}
