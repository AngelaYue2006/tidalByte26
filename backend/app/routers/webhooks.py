"""POST /api/webhooks/twilio/sms (signature, allowlist, YES or contact reply) and POST /api/webhooks/elevenlabs/post-call (transcript + data collection -> call_result).

The Twilio SMS route is here (#22); the ElevenLabs post-call route lands with #21. The SMS path trusts nothing
until `integrations.sms_twilio.parse_inbound` has verified the sender (mock: fixture people on the allowlist;
live: #27 adds the Twilio signature) and returns an InboundSms. An owner's YES approves the task that is
waiting, NO cancels it; anything else, or any unverified sender, is ignored. Every inbound, applied or not, is
answered 200 with an empty TwiML <Response/> (the documented no-action reply; a non-2xx makes Twilio retry) that
says nothing about any task (T9). Every reply is keyed by MessageSid (T8).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from sqlmodel import Session, select

from app import approvals
from app.events import emit_many
from app.models import Task
from app.people import load_owner
from integrations import sms_twilio

log = logging.getLogger("lifeline.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


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
        log.info("inbound SMS from a contact is not an approval; contact replies are handled by the contact route (#23)")
        return {"ok": True, "ignored": "not_owner"}
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
