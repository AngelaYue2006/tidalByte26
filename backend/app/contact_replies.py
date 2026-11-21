"""The contact's answer to the ride request, whichever way it arrives: the dashboard (routers/contacts.py) or an SMS
from the contact's allowlisted number (routers/webhooks.py calls `handle_contact_sms`). One place decides what a reply
means, records it and tells the owner, so both paths emit the same events (T8, T9, T10)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import texts
from app.events import EventBus, emit, emit_many
from app.models import Contact, Task
from app.orchestrator import Pipeline
from app.people import load_owner

log = logging.getLogger(__name__)

UNVERIFIED_SENDER = "UNVERIFIED_SENDER"
CONTACT_DECLINED = "CONTACT_DECLINED"

# A decline wins over an offer when both appear ("no, I can't, sorry" / "yes but I can't"): never a false ride.
_NO = re.compile(
    r"\b(no|nope|can'?t|cannot|unable|not able|won'?t|sorry|busy)\b", re.IGNORECASE
)
_YES = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok(?:ay)?|i can|can drive|i'?ll drive|will drive|count me in|on my way|absolutely|of course)\b",
    re.IGNORECASE,
)


def interpret(text: str) -> str | None:
    """'no', 'yes', or None when the text says neither. A contact's text never changes state on its own (rule 3): the
    reply becomes a state change only through `decline` or `confirm_ride` below."""
    if _NO.search(text or ""):
        return "no"
    if _YES.search(text or ""):
        return "yes"
    return None


def decline(
    engine: Engine,
    bus: EventBus,
    pipeline: Pipeline,
    task_id: str,
    contact_first: str,
    text: str,
) -> dict:
    """Record a decline once and keep waiting (T10). The owner is told, by event and by text; nothing confirms a ride."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        owner = load_owner(task.owner_id)
        booking = json.loads(task.booking_json) if task.booking_json else {}
    emit_many(
        engine,
        bus,
        task_id,
        [
            (
                "contact_reply",
                {
                    "contact": contact_first,
                    "text": text,
                    "offer": {"can_drive": False, "pickup_time": None},
                },
                "contact",
            ),
            (
                "task_updated",
                {
                    "status": "awaiting_contact",
                    "reason": CONTACT_DECLINED,
                    "message": f"{contact_first} can't drive this time; still waiting for a ride.",
                },
                "owner",
            ),
        ],
    )
    if booking:
        start = datetime.fromisoformat(booking["slot_start"])
        pipeline.send_sms(
            task_id,
            owner.phone_e164,
            texts.contact_declined_sms_user(contact_first, booking["clinic"], start),
            "contact_declined_owner",
        )
    return {"status": "awaiting_contact", "ride": "declined"}


def confirm_ride(
    engine: Engine,
    bus: EventBus,
    pipeline: Pipeline,
    task_id: str,
    contact_first: str,
    text: str,
    pickup_time: str | None,
) -> dict | None:
    """Take the one ride offer a wait accepts. None when it was already taken. Reply and confirmation commit together;
    on failure the claim is released so the contact can retry."""
    if not pipeline.claim_wait(task_id):
        return None
    with Session(engine) as session:
        booking_json = session.get(Task, task_id).booking_json
    pickup = pickup_time or default_pickup(booking_json)
    try:
        emit_many(
            engine,
            bus,
            task_id,
            [
                (
                    "contact_reply",
                    {
                        "contact": contact_first,
                        "text": text,
                        "offer": {"can_drive": True, "pickup_time": pickup},
                    },
                    "contact",
                ),
                (
                    "ride_confirmed",
                    {"driver": contact_first, "pickup_time": pickup},
                    "contact",
                ),
            ],
        )
    except Exception:
        pipeline.release_wait(task_id)
        raise
    pipeline.resume(task_id)
    return {"status": "ride_confirmed", "pickup_time": pickup}


def default_pickup(booking_json: str | None) -> str:
    """Thirty minutes before the appointment when the contact names no time."""
    if not booking_json:
        return ""
    start = datetime.fromisoformat(json.loads(booking_json)["slot_start"])
    return (start - timedelta(minutes=30)).isoformat()


def handle_contact_sms(
    engine: Engine,
    bus: EventBus,
    pipeline: Pipeline,
    sender_e164: str,
    text: str,
    message_sid: str,
) -> dict:
    """An inbound SMS that already passed the webhook's signature and allowlist checks. Returns a log-safe outcome.

    T8: the same MessageSid again replays the first outcome. T9: a sender who is not a contact on file is refused and
    the owner of the one task waiting for a contact is told that an unknown number wrote, without the number or the
    text. T10: a decline keeps the task waiting and tells the owner. Anything that is neither yes nor no is logged and
    ignored; the contact can text again or use the dashboard.
    """
    replayed = pipeline.replay("contact_sms", "", message_sid)
    if replayed is not None:
        return replayed
    with Session(engine) as session:
        contact = session.exec(
            select(Contact).where(Contact.phone_e164 == sender_e164)
        ).first()
        waiting_ids = [
            t.id
            for t in session.exec(
                select(Task).where(Task.status == "awaiting_contact")
            ).all()
            if pipeline.waiting(t.id)
        ]
        if contact is None:
            log.warning(
                "inbound sms %s: sender is not a contact on file (%d task(s) waiting)",
                message_sid,
                len(waiting_ids),
            )
            if len(waiting_ids) == 1:
                emit(
                    engine,
                    bus,
                    waiting_ids[0],
                    "task_updated",
                    {
                        "status": "awaiting_contact",
                        "reason": UNVERIFIED_SENDER,
                        "message": "A text from a number not on file was ignored.",
                    },
                    "owner",
                )
            return pipeline.remember(
                "contact_sms", "", message_sid, {"outcome": UNVERIFIED_SENDER}
            )
        task_id = next(
            (
                t.id
                for t in session.exec(
                    select(Task).where(
                        Task.status == "awaiting_contact",
                        Task.owner_id == contact.owner_id,
                    )
                ).all()
                if pipeline.waiting(t.id)
            ),
            None,
        )
        first = contact.name.split()[0]
    if task_id is None:
        log.info("inbound sms %s: contact replied but no task is waiting", message_sid)
        return pipeline.remember(
            "contact_sms", "", message_sid, {"outcome": "no_task_waiting"}
        )
    answer = interpret(text)
    if answer == "no":
        decline(engine, bus, pipeline, task_id, first, text)
        return pipeline.remember(
            "contact_sms", "", message_sid, {"outcome": "declined", "task_id": task_id}
        )
    if answer == "yes":
        result = confirm_ride(engine, bus, pipeline, task_id, first, text, None)
        outcome = (
            {"outcome": "ride_confirmed", "task_id": task_id}
            if result
            else {"outcome": "already_confirmed", "task_id": task_id}
        )
        return pipeline.remember("contact_sms", "", message_sid, outcome)
    log.info(
        "inbound sms %s: contact text is neither yes nor no (%d chars); still waiting",
        message_sid,
        len(text or ""),
    )
    return pipeline.remember(
        "contact_sms", "", message_sid, {"outcome": "unclear", "task_id": task_id}
    )
