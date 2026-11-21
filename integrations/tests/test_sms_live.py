"""Live SMS security and typed receipts using synthetic senders and fake Twilio."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from twilio.request_validator import RequestValidator

from integrations import sms_live
from integrations import sms_twilio as sms
from integrations.sms_inbound import SignedSMSForm

OWNER = "+15555550100"
CONTACT = "+15555550101"
SENDER = "+15555550102"
TOKEN = "synthetic-token"
ACCOUNT = "AC" + "0" * 32
URL = "https://lifeline.example/api/webhooks/twilio/sms"


@pytest.fixture(autouse=True)
def live_environment(monkeypatch):
    for key, value in {
        "SMS_MODE": "live",
        "DEMO_PHONE_ALLOWLIST": OWNER + "," + CONTACT,
        "TWILIO_AUTH_TOKEN": TOKEN,
        "TWILIO_ACCOUNT_SID": ACCOUNT,
        "TWILIO_PHONE_NUMBER": SENDER,
        "PUBLIC_BASE_URL": "https://lifeline.example",
    }.items():
        monkeypatch.setenv(key, value)


def envelope(sender=OWNER, body="YES", **updates):
    params = {
        "From": sender,
        "To": SENDER,
        "Body": body,
        "AccountSid": ACCOUNT,
        "MessageSid": "SM" + "1" * 32,
    }
    params.update(updates)
    signature = RequestValidator(TOKEN).compute_signature(URL, params)
    return SignedSMSForm(params, signature, {OWNER: "owner", CONTACT: "contact"})


@pytest.mark.parametrize(
    "sender,body,role", [(OWNER, "YES", "owner"), (CONTACT, "I can drive", "contact")]
)
def test_signed_owner_and_contact_are_typed(sender, body, role):
    fact = sms.parse_inbound(envelope(sender, body, task_id="untrusted-correlation"))
    assert fact.role == role and fact.body == body
    assert fact.from_e164 == sender and not fact.simulated
    assert fact.correlation == "untrusted-correlation"


def test_plain_form_cannot_smuggle_signature_or_role():
    with pytest.raises(RuntimeError, match="trusted webhook context"):
        sms.parse_inbound(
            {
                "From": OWNER,
                "Body": "YES",
                "role": "owner",
                "signature": "forged",
                "MessageSid": "fake",
            }
        )


@pytest.mark.parametrize("mutation", ["body", "sender", "signature", "url"])
def test_forged_or_changed_signature_is_rejected(monkeypatch, mutation):
    incoming = envelope()
    if mutation == "signature":
        incoming = replace(incoming, signature="forged")
    elif mutation == "url":
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://different.example")
    else:
        params = dict(incoming.parameters)
        params["Body" if mutation == "body" else "From"] = "changed"
        incoming = replace(incoming, parameters=params)
    with pytest.raises(RuntimeError, match="signature"):
        sms.parse_inbound(incoming)


def test_signed_unknown_sender_rejected():
    with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
        sms.parse_inbound(envelope("+15555550999"))


def test_allowlisted_sender_needs_backend_identity_mapping():
    incoming = replace(envelope(), roles={CONTACT: "contact"})
    with pytest.raises(RuntimeError, match="matched owner or contact"):
        sms.parse_inbound(incoming)


@pytest.mark.parametrize(
    "updates",
    [
        {"To": OWNER},
        {"AccountSid": "other"},
        {"MessageSid": ""},
        {"Body": ""},
        {"NumMedia": "1"},
    ],
)
def test_wrong_account_recipient_and_incomplete_or_media_messages_rejected(updates):
    with pytest.raises(RuntimeError):
        sms.parse_inbound(envelope(**updates))


@pytest.mark.parametrize(
    "base",
    [
        "http://lifeline.example",
        "https://user:pass@lifeline.example",
        "https://lifeline.example?key=x",
        "https://lifeline.example/#fragment",
    ],
)
def test_invalid_public_url_fails_closed(monkeypatch, base):
    monkeypatch.setenv("PUBLIC_BASE_URL", base)
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        sms.parse_inbound(envelope())


def test_send_allowlist_precedes_client_construction(monkeypatch):
    monkeypatch.setattr(
        sms_live,
        "TwilioSMSClient",
        lambda: pytest.fail("Client created before allowlist"),
    )
    with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
        sms.send("+15555550999", "Demo", "task:sms")


@pytest.mark.parametrize("text,key", [("", "step"), ("demo", ""), (" ", "step")])
def test_send_empty_inputs_fail_before_client(monkeypatch, text, key):
    monkeypatch.setattr(
        sms_live,
        "TwilioSMSClient",
        lambda: pytest.fail("Client created before validation"),
    )
    with pytest.raises(RuntimeError, match="text and idempotency"):
        sms.send(OWNER, text, key)


def test_send_returns_vendor_receipt_without_logging(monkeypatch, caplog, capsys):
    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, to, text):
            calls.append((to, text))
            return SimpleNamespace(sid="SM" + "2" * 32, status="queued")

    monkeypatch.setattr(sms_live, "TwilioSMSClient", Client)
    fact = sms.send(OWNER, "Synthetic demo message", "task:approval")
    assert not fact.simulated and fact.message_id == "SM" + "2" * 32
    assert fact.text == "Synthetic demo message" and calls == [(OWNER, fact.text)]
    assert not caplog.text and not capsys.readouterr().out


def test_unknown_mode_rejected(monkeypatch):
    monkeypatch.setenv("SMS_MODE", "typo")
    with pytest.raises(RuntimeError, match="SMS_MODE"):
        sms.parse_inbound(envelope())


def test_duplicate_form_fields_are_rejected():
    from starlette.datastructures import FormData

    original = envelope()
    duplicate = FormData([*original.parameters.items(), ("Body", "NO")])
    with pytest.raises(RuntimeError, match="duplicate"):
        sms.parse_inbound(replace(original, parameters=duplicate))


def test_unknown_twilio_fields_are_included_in_signature():
    original = envelope(FutureTwilioField="original")
    changed = dict(original.parameters)
    changed["FutureTwilioField"] = "tampered"
    with pytest.raises(RuntimeError, match="signature"):
        sms.parse_inbound(replace(original, parameters=changed))


def test_d16_signed_inbound_stays_live_with_mock_outbound(monkeypatch):
    monkeypatch.setenv("SMS_MODE", "mock")
    incoming = sms.parse_inbound(envelope())
    assert incoming.role == "owner" and incoming.simulated is False
    outgoing = sms.send(OWNER, "Synthetic pick", "task:pick")
    assert outgoing.simulated is True


def test_merged_backend_safely_rejects_bare_live_form(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    from app.routers.webhooks import handle_inbound

    # An accepted input would touch app.state; an untrusted one must not.
    assert handle_inbound(SimpleNamespace(), {"From": OWNER, "Body": "YES"}) == {
        "ok": False,
        "ignored": "unverified_sender",
    }
