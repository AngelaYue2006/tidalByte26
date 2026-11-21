"""Authenticated SMS facts; the HTTP route supplies header and identity context."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from twilio.request_validator import RequestValidator

from integrations.phone_policy import require_allowlisted
from integrations.types import InboundSms


@dataclass(frozen=True)
class SignedSMSForm:
    """Trusted route envelope. Never construct signature/roles from POST fields.

    parameters: the entire unmodified form, including unknown Twilio fields.
    signature: X-Twilio-Signature header.
    roles: phone -> owner/contact from the backend's identity store.
    The route must reject duplicate fields and use the exact documented URL,
    without a query string. Backend owns task matching and MessageSid deduplication.
    """

    parameters: Mapping[str, str]
    signature: str
    roles: Mapping[str, str]


def webhook_url():
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be an HTTPS origin without credentials or query"
        )
    return base + "/api/webhooks/twilio/sms"


def parse(form) -> InboundSms:
    if not isinstance(form, SignedSMSForm):
        raise RuntimeError(  # noqa: TRY004 - caller handles untrusted runtime context with RuntimeError
            "Live SMS requires trusted webhook context, not bare POST fields"
        )
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not token:
        raise RuntimeError("TWILIO_AUTH_TOKEN is required for signature verification")
    url = webhook_url()
    params = form.parameters
    # Reject ambiguous multipart/form encodings; validation uses every signed field.
    if hasattr(params, "getlist") and any(
        len(params.getlist(key)) != 1 for key in params
    ):
        raise RuntimeError("Inbound SMS contains duplicate fields")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in params.items()):
        raise RuntimeError("Inbound SMS form must contain text fields")
    if not form.signature or not RequestValidator(token).validate(
        url, params, form.signature
    ):
        raise RuntimeError("Inbound SMS signature verification failed")
    sender = params.get("From", "")
    require_allowlisted(sender)
    role = form.roles.get(sender)
    if role not in ("owner", "contact"):
        raise RuntimeError("UNVERIFIED_SENDER: no matched owner or contact")
    account, recipient = (
        os.getenv("TWILIO_ACCOUNT_SID", ""),
        os.getenv("TWILIO_PHONE_NUMBER", ""),
    )
    if (
        not account
        or not recipient
        or params.get("AccountSid") != account
        or params.get("To") != recipient
    ):
        raise RuntimeError(
            "Inbound SMS account or recipient does not match configuration"
        )
    if not params.get("MessageSid") or not params.get("Body", "").strip():
        raise RuntimeError("Inbound SMS needs MessageSid and Body")
    if params.get("NumMedia", "0") != "0":
        raise RuntimeError(
            "Inbound SMS supports text only; media is not fetched or stored"
        )
    return InboundSms(
        message_id=params["MessageSid"],
        from_e164=sender,
        body=params["Body"],
        role=role,
        correlation=params.get("task_id"),
        simulated=False,
    )
