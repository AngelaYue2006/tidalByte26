"""Issue #7: the inbound SMS stub answers Twilio with 200 and empty TwiML, drops unknown senders (T9) and repeats (T8), and logs no number or text."""

import logging

import pytest
from app.config import load_settings
from app.main import create_app
from app.routers.twilio_sms import record_inbound
from fastapi.testclient import TestClient

OWNER = "+15550100001"
STRANGER = "+15550100099"
BODY = "YES I can drive her"
ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "sqlite://",
    "DEMO_PHONE_ALLOWLIST": f"{OWNER},+15550100002",
}


@pytest.fixture
def client():
    with TestClient(create_app(load_settings(env_file=None, environ=ENV))) as c:
        yield c


def post(client, **fields):
    return client.post("/api/webhooks/twilio/sms", data=fields)


def test_allowlisted_sender_gets_empty_twiml_and_is_logged_without_number_or_text(
    client, caplog
):
    with caplog.at_level(logging.INFO, logger="lifeline.sms"):
        r = post(client, MessageSid="SM1", From=OWNER, To="+15550100100", Body=BODY)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/xml")
    assert "<Response></Response>" in r.text
    assert "'outcome': 'received'" in caplog.text
    assert "SM1" in caplog.text
    assert OWNER not in caplog.text
    assert BODY not in caplog.text


def test_repeated_message_sid_is_a_duplicate_not_a_second_receipt(client, caplog):
    with caplog.at_level(logging.INFO, logger="lifeline.sms"):
        post(client, MessageSid="SM2", From=OWNER, Body="YES")
        r = post(client, MessageSid="SM2", From=OWNER, Body="YES")
    assert r.status_code == 200
    assert caplog.text.count("'outcome': 'received'") == 1
    assert "'outcome': 'duplicate'" in caplog.text


def test_unknown_sender_is_rejected_with_the_same_200_and_no_leak(client, caplog):
    with caplog.at_level(logging.INFO, logger="lifeline.sms"):
        r = post(client, MessageSid="SM3", From=STRANGER, Body="hello?")
    assert r.status_code == 200
    assert "'outcome': 'rejected'" in caplog.text
    assert STRANGER not in caplog.text
    assert "hello" not in caplog.text


def test_record_inbound_checks_allowlist_before_remembering_the_sid():
    seen: set[str] = set()
    assert (
        record_inbound(seen, (OWNER,), {"MessageSid": "SM4", "From": STRANGER})[
            "outcome"
        ]
        == "rejected"
    )
    assert seen == set()
    assert record_inbound(seen, (OWNER,), {})["outcome"] == "ignored"
    assert record_inbound(
        seen, (OWNER,), {"MessageSid": "SM4", "From": OWNER, "Body": "YES"}
    ) == {
        "outcome": "received",
        "message_sid": "SM4",
        "body_chars": 3,
    }
    assert (
        record_inbound(seen, (OWNER,), {"MessageSid": "SM4", "From": OWNER})["outcome"]
        == "duplicate"
    )
