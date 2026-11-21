"""POST /api/webhooks/twilio/sms, the inbound SMS endpoint for the #7 round trip: answers Twilio fast with empty TwiML,
checks the sender against DEMO_PHONE_ALLOWLIST, records each MessageSid once and logs no phone number or text.
Signature validation arrives with integrations.sms_twilio.parse_inbound (#27); matching YES or a contact reply to a task with #22/#23."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/api/webhooks/twilio", tags=["webhooks"])
log = logging.getLogger("lifeline.sms")

# Empty TwiML is Twilio's documented "take no action" reply. A trial account logs error 12300 against it
# ("Direct TwiML XML is not supported during response" in the trial docs); the message is still received.
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def parse_form(raw_body: bytes) -> dict[str, str]:
    """Twilio posts application/x-www-form-urlencoded. Parsed by hand so the raw bytes stay available for the signature check later."""
    return dict(
        parse_qsl(raw_body.decode("utf-8", errors="replace"), keep_blank_values=True)
    )


def record_inbound(
    seen: set[str], allowlist: Collection[str], form: Mapping[str, str]
) -> dict[str, object]:
    """Decide what the stub does with one Twilio form; order is allowlist, then idempotency.

    Returns a summary that is safe to log: the MessageSid and counts, never the sender or the text."""
    message_sid = form.get("MessageSid", "")
    if not message_sid:
        return {"outcome": "ignored", "reason": "no MessageSid"}
    if form.get("From", "") not in allowlist:
        return {
            "outcome": "rejected",
            "message_sid": message_sid,
            "reason": "sender not on allowlist",
        }
    if message_sid in seen:
        return {"outcome": "duplicate", "message_sid": message_sid}
    seen.add(message_sid)
    return {
        "outcome": "received",
        "message_sid": message_sid,
        "body_chars": len(form.get("Body", "")),
    }


@router.post("/sms")
async def inbound_sms(request: Request) -> Response:
    """Always 200 with empty TwiML: Twilio retries on anything else, and a rejected sender must learn nothing."""
    form = parse_form(await request.body())
    summary = record_inbound(
        request.app.state.inbound_sms_seen,
        request.app.state.settings.demo_phone_allowlist,
        form,
    )
    log.info("twilio sms %s", summary)
    return Response(content=EMPTY_TWIML, media_type="text/xml")
