"""#115: build_deps wires ElevenLabs start_call when VOICE_MODE=live; booking confirm stays mock."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.adapters import VoiceLiveBridge, VoiceMockBridge, build_deps
from app.config import MissingSetting, load_settings
from integrations.google_places import find_clinics
from integrations.types import CallHandle, CallSpec, IntakeRequest, Window

from .test_config import LIVE_VOICE

CHICAGO = ZoneInfo("America/Chicago")
DEMO_NOW = datetime(2026, 11, 23, 9, 0, tzinfo=CHICAGO)


def test_build_deps_mock_keeps_voice_mock_bridge():
    settings = load_settings(env_file=None, environ={"VOICE_MODE": "mock"})
    deps = build_deps(settings)
    assert isinstance(deps.voice, VoiceMockBridge)
    assert deps.voice.live is False


def test_build_deps_live_requires_every_named_value():
    env = {k: v for k, v in LIVE_VOICE.items() if k != "TWILIO_PHONE_NUMBER"}
    settings = load_settings(env_file=None, environ=env)
    with pytest.raises(MissingSetting, match="TWILIO_PHONE_NUMBER"):
        build_deps(settings)


def test_build_deps_live_wires_elevenlabs_start_and_mock_confirm(monkeypatch):
    starts: list[str] = []

    def fake_start(spec: CallSpec) -> CallHandle:
        starts.append(spec.call_id)
        return CallHandle(call_id=spec.call_id, external_ref="conv-x", simulated=False)

    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550111,+15555550112,+15555550113")
    monkeypatch.setattr("integrations.voice_elevenlabs.start_call", fake_start)
    settings = load_settings(env_file=None, environ={**LIVE_VOICE, "CALL_RESULT_TIMEOUT_S": "90"})
    deps = build_deps(settings)
    assert isinstance(deps.voice, VoiceLiveBridge)
    assert deps.voice.live is True
    assert deps.call_result_timeout_s == 90.0

    window = Window(start=DEMO_NOW.replace(hour=0), end=DEMO_NOW.replace(day=29, hour=23))
    request = IntakeRequest(
        care_type="dental cleaning",
        budget_max=150,
        insurance_carrier="Delta Dental",
        time_range=window,
        needs_ride=True,
        search_area="near home",
    )
    clinic = find_clinics("dental cleaning", "near home", 1)[0]
    spec = CallSpec(clinic=clinic, request=request, windows=[window], call_id="live-a")

    handle = deps.voice.start_call(spec)
    assert starts == ["live-a"] and handle.external_ref == "conv-x" and handle.simulated is False

    confirmation = deps.voice.confirm_booking(spec, {"slot_start": "2026-11-26T09:30:00-06:00"})
    assert confirmation.status == "confirmed" and confirmation.simulated is True
