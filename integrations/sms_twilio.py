"""Typed mock/live SMS facts; no state writes or message logging."""

import hashlib
import os

from integrations.fixtures import read_fixture
from integrations.phone_policy import require_allowlisted
from integrations.types import InboundSms, MessageReceipt


def _mode():
    mode = os.getenv("SMS_MODE", "mock")
    if mode not in ("mock", "live"):
        raise RuntimeError("SMS_MODE must be mock or live")
    return mode


def send(to_e164, text, idempotency_key) -> MessageReceipt:
    mode = _mode()
    require_allowlisted(to_e164)
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or not isinstance(text, str)
        or not text.strip()
    ):
        raise RuntimeError("SMS text and idempotency key are required")
    if mode == "live":
        from integrations.sms_live import send as send_live

        return send_live(to_e164, text, idempotency_key)
    digest = hashlib.sha256(f"{to_e164}:{idempotency_key}".encode()).hexdigest()[:24]
    return MessageReceipt(message_id=f"mock-sms-{digest}", text=text, simulated=True)


def parse_inbound(form) -> InboundSms:
    if _mode() == "live":
        from integrations.sms_inbound import parse

        return parse(form)
    # Mock input is synthetic, not an authenticated Twilio webhook.
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
