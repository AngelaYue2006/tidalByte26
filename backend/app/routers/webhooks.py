"""POST /api/webhooks/twilio/sms (signature, allowlist, YES or contact reply) and POST /api/webhooks/elevenlabs/post-call (transcript + data collection -> call_result).

Two webhooks: the ElevenLabs post-call handler (#21) and the Twilio SMS handler (#22).

ElevenLabs order of checks: signature (ElevenLabs-Signature, HMAC-SHA256 over "<t>.<raw body>", 30-minute window),
then the event type, then the call it belongs to (conversation_id -> calls.external_ref, falling back to the
dynamic variable call_id), then the atomic per-call claim inside call_results. The synchronous work (Super, SQLite)
runs on a worker thread so the event loop keeps serving the parallel calls and the SSE stream; the delivery is
acknowledged with 200 only after the result is committed; a processing failure answers 500 so ElevenLabs retries,
and the atomic claim makes that retry safe.

Twilio: the SMS path trusts nothing
until `integrations.sms_twilio.parse_inbound` has verified the sender (mock: fixture people on the allowlist;
live: #27 adds the Twilio signature) and returns an InboundSms. An owner's YES approves the task that is
waiting, NO cancels it; anything else, or any unverified sender, is ignored. Every inbound, applied or not, is
answered 200 with an empty TwiML <Response/> (the documented no-action reply; a non-2xx makes Twilio retry) that
says nothing about any task (T9). Every reply is keyed by MessageSid (T8).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlmodel import Session, select

from app import approvals, call_results, contact_replies
from app.config import MissingSetting, Settings
from app.db import session_scope
from app.events import EventBus, emit_many
from app.models import Call, Task
from app.nemotron.ranker import ChatJSON, NvidiaChatClient
from app.people import load_owner
from integrations import sms_twilio

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


class ConversationMismatch(Exception):
    """The dynamic call_id names a call already bound to a different conversation."""


def find_call(engine: Engine, conversation_id: str | None, dynamic_call_id: str | None) -> tuple[Call, Task] | None:
    """conversation_id -> calls.external_ref. The dynamic call_id only binds a call that has no external_ref yet;
    a call already bound to another conversation is never touched (ConversationMismatch)."""
    with session_scope(engine) as session:
        call = None
        if conversation_id:
            call = session.exec(select(Call).where(Call.external_ref == conversation_id)).first()
        if call is None and dynamic_call_id:
            candidate = session.get(Call, dynamic_call_id)
            if candidate is not None:
                if candidate.external_ref and candidate.external_ref != conversation_id:
                    raise ConversationMismatch(f"call {dynamic_call_id!r} belongs to conversation {candidate.external_ref!r}, not {conversation_id!r}")
                if conversation_id and not candidate.external_ref:
                    candidate.external_ref = conversation_id
                    session.add(candidate)
                    session.flush()
                call = candidate
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
    try:
        found = find_call(engine, conversation_id, dynamic.get("call_id"))
    except ConversationMismatch as exc:
        log.warning("post-call webhook rejected: %s", exc)
        return {"ok": False, "ignored": "conversation_mismatch"}
    if found is None:
        log.warning("post-call webhook for unknown conversation %r; ignored", conversation_id)
        return {"ok": False, "ignored": "unknown_conversation"}
    call, task = found
    if payload.get("type") == "call_initiation_failure":
        outcome = call_results.record_call_failure(engine, bus, call, task, str(data.get("failure_reason") or "unknown"))
        outcome["task_id"] = task.id
        return outcome
    collection = (data.get("analysis") or {}).get("data_collection_results") or {}
    stamp = payload.get("event_timestamp")
    call_date = datetime.fromtimestamp(int(stamp), UTC) if isinstance(stamp, int | float) else datetime.now(UTC)
    outcome = call_results.record_call_result(
        engine, bus, call, task, collection, transcript_lines(data),
        call_date=call_date, timezone=settings.app_timezone, super_client=client,
    )
    outcome["task_id"] = task.id
    return outcome


@router.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    raw = await request.body()
    secret = settings.elevenlabs_webhook_secret
    if not secret:
        raise HTTPException(503, "ELEVENLABS_WEBHOOK_SECRET is not set; the mock voice adapter signs with the same secret")
    verify_signature(raw, request.headers.get(SIGNATURE_HEADER), secret)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "body must be JSON") from exc
    if not isinstance(payload, dict) or payload.get("type") not in HANDLED_TYPES:
        return {"ok": True, "ignored": "unhandled_type"}
    client = super_client(request) if payload.get("type") == "post_call_transcription" else None
    try:
        # Super and SQLite are synchronous: run them on a worker thread so the three parallel calls and the SSE stream
        # keep being served, and still answer only once the result is durable.
        outcome = await run_in_threadpool(process_post_call, request.app.state.engine, request.app.state.bus, settings, payload, client)
    except Exception as exc:  # anything not committed: say so, ElevenLabs retries, the claim keeps the retry safe
        log.exception("post-call webhook processing failed; asking for a retry")
        raise HTTPException(500, "post-call processing failed; retry") from exc
    # Live calling waits on resume (#116). Never wake approval/contact waits; drop task_id from the HTTP body.
    task_id = outcome.pop("task_id", None)
    if task_id and not outcome.get("duplicate"):
        with Session(request.app.state.engine) as session:
            task = session.get(Task, task_id)
            status = task.status if task is not None else None
        if status == "calling":
            request.app.state.pipeline.resume(task_id)
    return {"ok": True, "accepted": payload["type"], **outcome}

def _waiting_task(engine, owner_id: str, correlation: str | None) -> Task | None:
    """The task this reply answers: the correlated one when the SMS names it, else the owner's task awaiting approval,
    else the owner's latest task (so a repeated YES after approval is answered as already applied, not as a mystery)."""
    with Session(engine) as session:
        if correlation:
            task = session.get(Task, correlation)
            return task if task is not None and task.owner_id == owner_id else None
        waiting = session.exec(
            select(Task).where(Task.owner_id == owner_id, Task.status == "awaiting_approval").order_by(Task.created_at.desc())
        ).first()
        if waiting is not None:
            return waiting
        return session.exec(select(Task).where(Task.owner_id == owner_id).order_by(Task.created_at.desc(), Task.id.desc())).first()


EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@router.post("/twilio/sms", response_class=Response)
async def twilio_sms(request: Request) -> Response:
    """Always 200 with empty TwiML, the documented no-action reply, for every inbound: applied, ignored or duplicate.
    (A trial account logs error 12300 "Direct TwiML XML is not supported" on this reply; the message is still received.)
    The outcome goes to the log and to `handle_inbound` for tests; the task state is the record."""
    outcome = handle_inbound(request.app, await request.form())
    log.info("inbound SMS outcome: %s", {k: v for k, v in outcome.items() if k != "task_id"})
    return Response(content=EMPTY_TWIML, media_type="text/xml")


def handle_inbound(app, form) -> dict:
    """Verify the sender, read the answer, apply it once. Returns what happened (for the log and tests), never raises for
    bad input: an unverified sender or a malformed form is simply ignored."""
    try:
        inbound = sms_twilio.parse_inbound(form)
    except RuntimeError as exc:
        # UNVERIFIED_SENDER or a malformed form: say nothing about any task.
        log.warning("inbound SMS ignored: %s", str(exc).split(":")[0])
        return {"ok": False, "ignored": "unverified_sender"}
    if inbound.role != "owner":
        # The contact's answer to the ride request (#23): yes confirms once, no keeps waiting and tells the owner.
        outcome = contact_replies.handle_contact_sms(app.state.engine, app.state.bus, app.state.pipeline, inbound.from_e164, inbound.body, inbound.message_id)
        return {"ok": True, "role": "contact", **outcome}
    decision = approvals.decision_from_text(inbound.body)
    if decision is None:
        return {"ok": True, "ignored": "not_an_answer"}
    engine, bus, pipeline = app.state.engine, app.state.bus, app.state.pipeline
    owner_id = _owner_id_for(inbound.from_e164)
    if owner_id is None:
        return {"ok": False, "ignored": "unverified_sender"}
    task = _waiting_task(engine, owner_id, inbound.correlation)
    if task is None:
        log.info("owner SMS %s but no task of theirs is awaiting approval", decision)
        return {"ok": True, "ignored": "nothing_waiting"}
    try:
        reply = approvals.apply_decision(engine, bus, pipeline, task.id, owner_id, decision, "sms", inbound.message_id, emit=emit_many)
    except approvals.WrongState as exc:
        return {"ok": True, "ignored": "not_awaiting_approval", "status": exc.status}
    return {"ok": True, "task_id": task.id, **reply}


def _owner_id_for(phone_e164: str) -> str | None:
    """The owner whose on-device record carries this verified number. One owner in the demo; the lookup stays explicit."""
    from app.people import (
        _users,  # the fixture people, the same source parse_inbound verified against
    )

    owner = _users()["owner"]
    if owner.get("phone_e164") == phone_e164:
        return load_owner(owner["id"]).id
    return None
