"""Synthetic ElevenLabs outbound requests; no real calls or secrets."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from integrations import elevenlabs_api as api
from integrations import voice_elevenlabs as voice
from integrations.tests.elevenlabs_fakes import (
    PHONE,
    agent,
    install,
    number,
)
from integrations.tests.elevenlabs_fakes import (
    call as call,  # noqa: PLC0414 - explicit pytest fixture export
)
from integrations.tests.elevenlabs_fakes import (
    environment as environment,  # noqa: PLC0414 - explicit pytest fixture export
)
from integrations.types import CallHandle


def test_outbound_shape_typed_handle_and_minimal_redacted_context(
    monkeypatch, call, caplog
):
    requests = install(monkeypatch)
    result = voice.start_call(call)
    assert isinstance(result, CallHandle) and not result.simulated
    assert result.call_id == call.call_id and result.external_ref == "conversation-test"
    assert len(requests) == 3
    body = json.loads(requests[-1].content)
    assert body["to_number"] == PHONE and body["call_recording_enabled"] is False
    context = body["conversation_initiation_client_data"]
    assert context["custom_llm_extra_body"] == {
        "call_id": call.call_id,
        "proxy_secret": "synthetic-proxy-secret",
    }
    variables = context["dynamic_variables"]
    assert (
        variables["call_id"] == call.call_id
        and variables["clinic_name"] == call.clinic.name
    )
    assert (
        variables["care_type"] == "dental cleaning"
        and variables["insurance_carrier"] == "Delta Dental"
    )
    assert json.loads(variables["windows"])[0]["start"].endswith("-06:00")
    assert set(variables) == {
        "call_id",
        "clinic_name",
        "care_type",
        "budget_max",
        "insurance_carrier",
        "windows",
    }
    assert call.clinic.address not in requests[-1].content.decode()
    assert "member_id" not in requests[-1].content.decode()
    assert "synthetic-proxy-secret" not in caplog.text and PHONE not in caplog.text


def test_unknown_phone_refused_before_configuration_or_http(monkeypatch, call):
    call.clinic.phone_e164 = "+15555550999"
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
        voice.start_call(call)


@pytest.mark.parametrize(
    "field",
    [
        "ELEVENLABS_AGENT_ID",
        "ELEVENLABS_PHONE_NUMBER_ID",
        "ELEVENLABS_WEBHOOK_SECRET",
        "LLM_PROXY_SECRET",
    ],
)
def test_missing_configuration_prevents_calls(monkeypatch, call, field):
    monkeypatch.delenv(field)
    with pytest.raises(RuntimeError, match=field):
        voice.start_call(call)


@pytest.mark.parametrize(
    "setting",
    [
        "disclosure",
        "audio",
        "extra_body",
        "proxy_url",
        "audio_webhook",
        "webhook_missing",
    ],
)
def test_unsafe_agent_configuration_prevents_outbound(monkeypatch, call, setting):
    config = agent()
    if setting == "disclosure":
        config["conversation_config"]["agent"]["first_message"] = "Hello"
    elif setting == "audio":
        config["platform_settings"]["privacy"]["record_voice"] = True
    elif setting == "extra_body":
        config["platform_settings"]["overrides"]["custom_llm_extra_body"] = False
    elif setting == "proxy_url":
        config["conversation_config"]["agent"]["prompt"]["custom_llm"]["url"] = (
            "https://other.example/v1"
        )
    elif setting == "audio_webhook":
        config["platform_settings"]["workspace_overrides"]["webhooks"]["events"].append(
            "audio"
        )
    else:
        config["platform_settings"]["workspace_overrides"]["webhooks"] = {}
    requests = install(monkeypatch, agent_data=config)
    with pytest.raises(RuntimeError):
        voice.start_call(call)
    assert all(r.method == "GET" for r in requests)


@pytest.mark.parametrize("setting", ["provider", "supports_outbound", "assigned_agent"])
def test_wrong_phone_configuration_prevents_calls(monkeypatch, call, setting):
    config = number()
    config[setting] = {
        "provider": "sip_trunk",
        "supports_outbound": False,
        "assigned_agent": {"agent_id": "other"},
    }[setting]
    requests = install(monkeypatch, number_data=config)
    with pytest.raises(RuntimeError, match="phone"):
        voice.start_call(call)
    assert all(r.method == "GET" for r in requests)


@pytest.mark.parametrize(
    "result",
    [
        {"success": False, "message": "private vendor details"},
        {"success": True},
        {"success": "true", "conversation_id": "fake"},
    ],
)
def test_rejected_or_incomplete_acceptance_never_returns_handle(
    monkeypatch, call, result
):
    install(monkeypatch, result=result)
    with pytest.raises(RuntimeError) as error:
        voice.start_call(call)
    assert "private vendor details" not in str(error.value)


@pytest.mark.parametrize("kind", ["timeout", "http", "redirect", "invalid_json"])
def test_network_failure_sanitized_and_never_retried(monkeypatch, call, kind):
    def failure(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private credentials", request=request)
        if kind == "invalid_json":
            return httpx.Response(200, text="private response")
        return httpx.Response(429 if kind == "http" else 302, text="private response")

    requests = install(monkeypatch, failure=failure)
    with pytest.raises(RuntimeError) as error:
        voice.start_call(call)
    assert len([r for r in requests if r.method == "POST"]) == 1
    assert "private" not in str(error.value)


def test_live_booking_fails_before_any_outbound_request(call):
    with pytest.raises(RuntimeError, match="booking"):
        voice.confirm_booking(call, "Thu 9:30")


def test_mock_and_unknown_modes_cannot_make_vendor_requests(monkeypatch, call):
    for mode in ["mock", "typo"]:
        monkeypatch.setenv("VOICE_MODE", mode)
        with pytest.raises(RuntimeError, match="VOICE_MODE"):
            voice.start_call(call)


def test_allowlist_is_rechecked_after_preflight(monkeypatch, call):
    class Client:
        settings = SimpleNamespace(
            agent_id="agent-test", phone_id="phone-test", proxy_secret="synthetic"
        )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def preflight(self):
            monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "")

        def request(self, *args):
            pytest.fail("Dial after allowlist removal")

    monkeypatch.setattr(api, "ElevenLabsClient", Client)
    with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
        voice.start_call(call)


def test_three_outbound_calls_can_overlap(monkeypatch, call):
    gate = threading.Barrier(3)
    calls = [call.model_copy(deep=True) for _ in range(3)]
    phones = ["+15555550111", "+15555550112", "+15555550113"]
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", ",".join(phones))
    for i, spec in enumerate(calls):
        spec.call_id = f"concurrent-{i}"
        spec.clinic.phone_e164 = phones[i]

    def result(request):
        gate.wait(timeout=3)
        call_id = json.loads(request.content)["conversation_initiation_client_data"][
            "dynamic_variables"
        ]["call_id"]
        return httpx.Response(
            200, json={"success": True, "conversation_id": "conversation-" + call_id}
        )

    requests = install(monkeypatch, result=result)
    with ThreadPoolExecutor(max_workers=3) as pool:
        handles = list(pool.map(voice.start_call, calls))
    assert [handle.call_id for handle in handles] == [call.call_id for call in calls]
    assert len({handle.external_ref for handle in handles}) == 3
    assert len([r for r in requests if r.method == "POST"]) == 3


def test_mock_mode_delegates_without_vendor_access(monkeypatch, call):
    from integrations import voice_mock
    from integrations.types import Confirmation

    monkeypatch.setenv("VOICE_MODE", "mock")
    monkeypatch.setattr(
        api, "ElevenLabsClient", lambda: pytest.fail("Mock opened vendor client")
    )
    handle = CallHandle(call_id=call.call_id, external_ref="mock-call", simulated=True)
    receipt = Confirmation(
        status="confirmed",
        confirmation_ref="mock-booking",
        evidence="Synthetic receptionist fixture",
        simulated=True,
    )
    monkeypatch.setattr(voice_mock, "start_call", lambda spec: handle, raising=False)
    monkeypatch.setattr(
        voice_mock, "confirm_booking", lambda spec, slot: receipt, raising=False
    )
    assert voice.start_call(call) == handle
    assert voice.confirm_booking(call, "Thu 9:30") == receipt
