"""Twilio transport preflight, retry and privacy checks without vendor HTTP."""

from types import SimpleNamespace

import pytest
from requests.exceptions import ReadTimeout
from twilio.base.exceptions import TwilioRestException

from integrations import sms_live

OWNER = "+15555550100"
SENDER = "+15555550102"


@pytest.fixture
def transport(monkeypatch):
    for key, value in {
        "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TWILIO_AUTH_TOKEN": "synthetic-token",
        "TWILIO_PHONE_NUMBER": SENDER,
        "DEMO_PHONE_ALLOWLIST": OWNER,
    }.items():
        monkeypatch.setenv(key, value)
    state = SimpleNamespace(
        numbers=[SimpleNamespace(phone_number=SENDER, capabilities={"sms": True})],
        creates=[],
        message=SimpleNamespace(sid="SM" + "1" * 32, status="queued"),
        failure=None,
        http=None,
    )

    def create(**kwargs):
        state.creates.append(kwargs)
        if state.failure:
            raise state.failure
        return state.message

    def client(account, token, http_client):
        state.http = http_client
        return SimpleNamespace(
            messages=SimpleNamespace(create=create),
            incoming_phone_numbers=SimpleNamespace(
                stream=lambda **kwargs: iter(state.numbers)
            ),
        )

    monkeypatch.setattr(sms_live, "Client", client)
    return state


def test_owned_sms_sender_and_private_sdk_logging(transport, caplog):
    result = sms_live.send(OWNER, "Synthetic SMS", "task:step")
    assert not result.simulated
    assert transport.creates == [
        {"to": OWNER, "from_": SENDER, "body": "Synthetic SMS"}
    ]
    assert transport.http.timeout == 20 and transport.http.logger.disabled
    transport.http.log_request(
        {
            "method": "POST",
            "url": "private-account-url",
            "headers": {},
            "params": {},
            "data": {"Body": "private message"},
        }
    )
    assert not caplog.text


@pytest.mark.parametrize("kind", ["unowned", "voice_only"])
def test_sender_preflight_blocks_before_create(transport, kind):
    if kind == "unowned":
        transport.numbers = []
    else:
        transport.numbers[0].capabilities = {"voice": True, "sms": False}
    with pytest.raises(RuntimeError, match="owned and SMS-capable"):
        sms_live.send(OWNER, "Synthetic", "task:step")
    assert not transport.creates


@pytest.mark.parametrize(
    "error",
    [
        ReadTimeout("private-url-and-token"),
        TwilioRestException(400, "private-url", msg="private-vendor-message"),
    ],
)
def test_submission_failure_is_sanitized_and_never_retried(transport, error):
    transport.failure = error
    with pytest.raises(RuntimeError, match="delivery is unverified") as caught:
        sms_live.send(OWNER, "Synthetic", "task:step")
    assert len(transport.creates) == 1
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "sid,status",
    [("bad", "queued"), ("SM" + "1" * 32, "failed"), ("SM" + "1" * 32, "undelivered")],
)
def test_failed_or_invalid_receipt_is_not_accepted(transport, sid, status):
    transport.message.sid, transport.message.status = sid, status
    with pytest.raises(RuntimeError, match="accepted message receipt"):
        sms_live.send(OWNER, "Synthetic", "task:step")


def test_direct_transport_cannot_bypass_allowlist(transport):
    with (
        sms_live.TwilioSMSClient() as client,
        pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"),
    ):
        client.send("+15555550999", "Synthetic")
    assert not transport.creates
