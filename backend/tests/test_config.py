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


MODEL_ENV = {"NEMOTRON_NANO_TAG": "nano:4bit", "NEMOTRON_LIGHTNING_ID": "nvidia/lightning", "NEMOTRON_SUPER_ID": "nvidia/super"}
LIVE_VOICE = {**ALL_MOCK, **MODEL_ENV, "VOICE_MODE": "live", "NVIDIA_API_KEY": "x", "ELEVENLABS_API_KEY": "x",
              "ELEVENLABS_AGENT_ID": "x", "ELEVENLABS_PHONE_NUMBER_ID": "x", "ELEVENLABS_WEBHOOK_SECRET": "x", "LLM_PROXY_SECRET": "x",
              "PUBLIC_BASE_URL": "https://example.ngrok.app", "DEMO_PHONE_ALLOWLIST": "+15550100001"}


def test_live_voice_with_every_value_set_starts():
    load_settings(env_file=None, environ=LIVE_VOICE).validate_startup()


@pytest.mark.parametrize("model_env", sorted(MODEL_ENV))
def test_live_voice_without_any_one_model_id_raises_at_startup(model_env):
    env = {k: v for k, v in LIVE_VOICE.items() if k != model_env}
    with pytest.raises(MissingSetting, match=model_env):
        load_settings(env_file=None, environ=env).validate_startup()


@pytest.mark.parametrize("live_mode", ["PLACES_MODE", "CALENDAR_MODE", "SMS_MODE"])
def test_any_live_adapter_requires_all_three_model_ids(live_mode):
    s = load_settings(env_file=None, environ={**ALL_MOCK, live_mode: "live"})
    assert s.any_live
    with pytest.raises(MissingSetting) as exc:
        s.validate_startup()
    for name in MODEL_ENV:
        assert name in str(exc.value)


def test_all_mock_needs_no_model_id():
    s = load_settings(env_file=None, environ=ALL_MOCK)
    assert not s.any_live
    s.validate_startup()


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
