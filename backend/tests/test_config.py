"""Issue #5: settings come from .env with no invented model IDs, and live mode fails at startup when a value is missing."""

import pytest
from app.config import MissingSetting, Settings, load_settings

ALL_MOCK = {"VOICE_MODE": "mock", "PLACES_MODE": "fixture", "CALENDAR_MODE": "mock", "SMS_MODE": "mock"}


def test_defaults_are_mock_and_model_ids_are_none():
    s = load_settings(env_file=None, environ={})
    assert s.modes == {
        "voice": "mock", "places": "fixture", "calendar": "mock", "sms": "mock", "transport": "fixture", "live_stream": "sse",
    }
    assert s.nemotron_nano_tag is None
    assert s.nemotron_lightning_id is None
    assert s.nemotron_super_id is None
    s.validate_startup()  # nothing live, nothing required


def test_empty_strings_in_env_count_as_unset():
    s = load_settings(env_file=None, environ={"NEMOTRON_SUPER_ID": "   ", "DEMO_PHONE_ALLOWLIST": ""})
    assert s.nemotron_super_id is None
    assert s.demo_phone_allowlist == ()


def test_allowlist_is_parsed_from_comma_separated_e164():
    s = load_settings(env_file=None, environ={"DEMO_PHONE_ALLOWLIST": "+15550100001, +15550100002,"})
    assert s.demo_phone_allowlist == ("+15550100001", "+15550100002")


def test_live_voice_without_lightning_id_raises_at_startup():
    env = {**ALL_MOCK, "VOICE_MODE": "live", "NVIDIA_API_KEY": "x", "ELEVENLABS_API_KEY": "x", "ELEVENLABS_AGENT_ID": "x",
           "ELEVENLABS_PHONE_NUMBER_ID": "x", "LLM_PROXY_SECRET": "x", "PUBLIC_BASE_URL": "https://example.ngrok.app",
           "DEMO_PHONE_ALLOWLIST": "+15550100001"}
    with pytest.raises(MissingSetting, match="NEMOTRON_LIGHTNING_ID"):
        load_settings(env_file=None, environ=env).validate_startup()
    load_settings(env_file=None, environ={**env, "NEMOTRON_LIGHTNING_ID": "some/id"}).validate_startup()


def test_live_sms_and_calendar_name_every_missing_value():
    s = load_settings(env_file=None, environ={**ALL_MOCK, "SMS_MODE": "live", "CALENDAR_MODE": "live"})
    with pytest.raises(MissingSetting) as exc:
        s.validate_startup()
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "GOOGLE_REFRESH_TOKEN"):
        assert name in str(exc.value)


def test_require_model_never_guesses():
    s = Settings()
    with pytest.raises(MissingSetting, match="NEMOTRON_SUPER_ID"):
        s.require_model("super")
    assert Settings(nemotron_super_id="nvidia/x").require_model("super") == "nvidia/x"


def test_unknown_mode_value_is_rejected():
    with pytest.raises(ValueError):
        load_settings(env_file=None, environ={"VOICE_MODE": "real"})
