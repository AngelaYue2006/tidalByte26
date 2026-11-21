"""Simulated SMS facts only. No Twilio calls, state writes or message logging."""

import hashlib
import os

from integrations.fixtures import read_fixture
from integrations.phone_policy import require_allowlisted
from integrations.types import InboundSms, MessageReceipt


def _require_mock():
    if os.getenv("SMS_MODE", "mock") != "mock":
        raise RuntimeError("SMS live mode is not implemented; use SMS_MODE=mock")


def send(to_e164, text, idempotency_key) -> MessageReceipt:
    _require_mock()
    require_allowlisted(to_e164)
    if not idempotency_key or not text:
        raise RuntimeError("SMS text and idempotency key are required")
    digest = hashlib.sha256(f"{to_e164}:{idempotency_key}".encode()).hexdigest()[:24]
    return MessageReceipt(message_id=f"mock-sms-{digest}", text=text, simulated=True)


def parse_inbound(form) -> InboundSms:
    # Mock input is synthetic, not an authenticated Twilio webhook. Live must fail closed.
    _require_mock()
    sender = form.get("From", "")
    require_allowlisted(sender)
    users = read_fixture("users.json")
    people = [users["owner"], *users["contacts"]]
    person = next((p for p in people if p["phone_e164"] == sender), None)
    if person is None:
        raise RuntimeError("UNVERIFIED_SENDER: no synthetic owner or contact matches")
    if not form.get("MessageSid") or not form.get("Body"):
        raise RuntimeError("Inbound SMS needs MessageSid and Body")
    return InboundSms(
        message_id=form["MessageSid"],
        from_e164=sender,
        body=form["Body"],
        role=person["role"],
        correlation=form.get("task_id"),
        simulated=True,
    )
