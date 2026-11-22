"""Synthetic ElevenLabs configuration and HTTP fixtures for voice tests."""

import httpx
import pytest

from integrations import elevenlabs_api as api
from integrations.fixtures import read_fixture
from integrations.types import CallSpec, Clinic, IntakeRequest, Window

PHONE = "+15555550111"
OPENING = "Hi, I'm an AI assistant calling for a patient."


def agent():
    return {
        "agent_id": "agent-test",
        "conversation_config": {
            "agent": {
                "first_message": OPENING,
                "prompt": {
                    "llm": "custom-llm",
                    "custom_llm": {"url": "https://demo.example/v1"},
                },
            }
        },
        "platform_settings": {
            "privacy": {"record_voice": False},
            "overrides": {"custom_llm_extra_body": True},
            "workspace_overrides": {
                "webhooks": {
                    "post_call_webhook_id": "hook-test",
                    "events": ["transcript", "call_initiation_failure"],
                }
            },
        },
    }


def number():
    return {
        "provider": "twilio",
        "phone_number_id": "phone-test",
        "supports_outbound": True,
        "assigned_agent": {"agent_id": "agent-test"},
    }


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for key, value in {
        "VOICE_MODE": "live",
        "ELEVENLABS_API_KEY": "synthetic-key",
        "ELEVENLABS_AGENT_ID": "agent-test",
        "ELEVENLABS_PHONE_NUMBER_ID": "phone-test",
        "ELEVENLABS_WEBHOOK_SECRET": "synthetic-webhook-secret",
        "PUBLIC_BASE_URL": "https://demo.example",
        "LLM_PROXY_SECRET": "synthetic-proxy-secret",
        "DEMO_PHONE_ALLOWLIST": PHONE,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        httpx.Client, "send", lambda *a, **k: pytest.fail("Real HTTP forbidden")
    )


@pytest.fixture
def call():
    row = read_fixture("clinics.json")["clinics"][0]
    clinic = Clinic(
        **{
            k: row[k]
            for k in ("name", "phone_e164", "address", "lat", "lng", "place_id")
        },
        simulated=True,
    )
    return CallSpec(
        clinic=clinic,
        call_id="synthetic-call",
        windows=[
            Window(start="2026-11-26T09:00:00-06:00", end="2026-11-26T12:00:00-06:00")
        ],
        request=IntakeRequest(
            care_type="dental cleaning",
            budget_max=150,
            insurance_carrier="Delta Dental",
            time_range={"start": "2026-11-23T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
            needs_ride=True,
            search_area="Chicago",
            dropped_fields=["member_id"],
        ),
    )


def install(
    monkeypatch, *, agent_data=None, number_data=None, result=None, failure=None
):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["xi-api-key"] == "synthetic-key"
        if request.url.path.endswith("/agents/agent-test"):
            return httpx.Response(
                200, json=agent_data if agent_data is not None else agent()
            )
        if request.url.path.endswith("/phone-numbers/phone-test"):
            return httpx.Response(
                200, json=number_data if number_data is not None else number()
            )
        if failure:
            return failure(request)
        if callable(result):
            return result(request)
        return httpx.Response(
            200,
            json=result
            if result is not None
            else {
                "success": True,
                "conversation_id": "conversation-test",
                "callSid": "not-used",
            },
        )

    original = api.ElevenLabsClient
    monkeypatch.setattr(
        api,
        "ElevenLabsClient",
        lambda: original(transport=httpx.MockTransport(handler)),
    )

    # Let MockTransport use the real request/send implementation with no sockets.
    def send(self, request, **kwargs):
        return self._transport.handle_request(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    return requests
