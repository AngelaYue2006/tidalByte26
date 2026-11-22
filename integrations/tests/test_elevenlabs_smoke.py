"""Safety checks for the manual-call harness; no vendor HTTP."""

from unittest.mock import Mock

import pytest

from integrations.elevenlabs_smoke import context, conversation_checks, spec_for
from integrations.fixtures import read_fixture


@pytest.fixture
def inputs():
    return ({"intake": {
        "care_type": "dental cleaning", "time_range": {
            "start": "2026-11-23T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
        "needs_ride": False, "search_area": "Chicago"},
        "windows": [{"start": "2026-11-26T09:00:00Z", "end": "2026-11-26T10:00:00Z"}]},
        {"call_id": "synthetic-call", "clinic": read_fixture("clinics.json")["clinics"][0]["name"]})


def test_spec_uses_backend_facts_and_only_clinic_contract_fields(monkeypatch, inputs):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550901")
    task, call = inputs
    spec = spec_for(task, call, "+15555550901")
    assert spec.call_id == call["call_id"]
    assert spec.clinic.phone_e164 == "+15555550901"
    assert spec.request.care_type == task["intake"]["care_type"]
    assert spec.windows[0].model_dump(mode="json") == task["windows"][0]


def test_spec_rejects_unallowlisted_destination(monkeypatch, inputs):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550901")
    with pytest.raises(RuntimeError, match="allowlist"):
        spec_for(*inputs, "+15555550902")


def test_spec_rejects_unknown_clinic(monkeypatch, inputs):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550901")
    task, call = inputs
    call["clinic"] = "Unrecognized clinic"
    with pytest.raises(RuntimeError, match="synthetic clinic"):
        spec_for(task, call, "+15555550901")


@pytest.mark.parametrize("calls", [[], [{"call_id": "synthetic-call", "status": "done"}], [{"call_id": "synthetic-call", "result": {"price": 1}}],
                                  [{"call_id": "synthetic-call"}, {"call_id": "synthetic-call"}]])
def test_context_refuses_missing_completed_or_ambiguous_calls(calls):
    client = Mock()
    client.get.return_value.json.return_value = [{"calls": calls}]
    with pytest.raises(RuntimeError, match="fresh backend call"):
        context(client, "synthetic-call")


def test_disclosure_check_uses_spoken_vendor_opening_without_returning_text():
    checks = conversation_checks({"transcript": [
        {"role": "agent", "message": "Hi, I'm an AI assistant calling for a patient.", "interrupted": False},
        {"role": "user", "message": "Synthetic receptionist line"},
        {"role": "agent", "message": "What does a cleaning cost?", "interrupted": True},
    ], "has_audio": False})
    assert checks == {"opening_discloses_ai": True, "interrupted_agent_turns": 1,
                      "repeated_agent_lines": 0, "stored_audio": False}
    assert "Synthetic" not in str(checks) and "cleaning" not in str(checks)


def test_conversation_checks_report_missing_disclosure_and_audio_storage():
    checks = conversation_checks({"transcript": [{"role": "agent", "message": "Hello"}],
                                  "has_user_audio": True})
    assert checks["opening_discloses_ai"] is False
    assert checks["stored_audio"] is True
