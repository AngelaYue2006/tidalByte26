"""Issue #5: the app starts, creates the five tables and serves GET /api/health without leaking secrets."""

import pytest
from app.config import MissingSetting, load_settings
from app.main import create_app
from app.models import TABLES
from fastapi.testclient import TestClient
from sqlalchemy import inspect

SECRET = "leak-canary-1234567890"
ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "sqlite://",
    "NEMOTRON_NANO_TAG": "nemotron-nano:4bit-test",
    "NEMOTRON_SUPER_ID": "nvidia/super-test",
    "NVIDIA_API_KEY": SECRET,
    "TWILIO_AUTH_TOKEN": SECRET,
    "DEMO_PHONE_ALLOWLIST": "+15550100001,+15550100002",
    "PUBLIC_BASE_URL": "https://secret-tunnel.ngrok.app",
}


@pytest.fixture
def client():
    app = create_app(load_settings(env_file=None, environ=ENV))
    with TestClient(app) as c:
        yield c


def test_health_reports_modes_and_models_without_secrets(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["modes"] == {
        "voice": "mock", "places": "fixture", "calendar": "mock", "sms": "mock", "transport": "fixture", "live_stream": "sse",
    }
    assert body["models"] == {"nano": "nemotron-nano:4bit-test", "lightning": None, "super": "nvidia/super-test"}
    assert body["allowlist_size"] == 2
    text = r.text
    assert SECRET not in text
    assert "ngrok" not in text
    assert "+1555" not in text


def test_startup_creates_every_table_from_the_data_model(client):
    engine = client.app.state.engine
    assert set(inspect(engine).get_table_names()) >= set(TABLES)
    columns = {c["name"] for c in inspect(engine).get_columns("tasks")}
    assert columns == {
        "id", "owner_id", "status", "intake_json", "windows_json", "decision_json", "booking_json", "transport_json",
        "created_at", "updated_at",
    }
    assert {c["name"] for c in inspect(engine).get_columns("events")} == {"id", "task_id", "type", "payload_json", "visibility", "at"}


def test_create_app_refuses_live_mode_with_missing_values():
    with pytest.raises(MissingSetting, match="NEMOTRON_LIGHTNING_ID"):
        create_app(load_settings(env_file=None, environ={**ENV, "VOICE_MODE": "live"}))


def test_create_app_starts_in_live_mode_when_every_value_is_set(monkeypatch):
    """#115: VOICE_MODE=live constructs the live bridge; no network (start_call patched)."""
    from app.adapters import VoiceLiveBridge
    from integrations.types import CallHandle

    monkeypatch.setattr(
        "integrations.voice_elevenlabs.start_call",
        lambda spec: CallHandle(call_id=spec.call_id, external_ref="conv", simulated=False),
    )
    live_env = {
        **ENV,
        "VOICE_MODE": "live",
        "NEMOTRON_LIGHTNING_ID": "nvidia/lightning-test",
        "ELEVENLABS_API_KEY": "x",
        "ELEVENLABS_AGENT_ID": "x",
        "ELEVENLABS_PHONE_NUMBER_ID": "x",
        "ELEVENLABS_WEBHOOK_SECRET": "x",
        "LLM_PROXY_SECRET": "x",
        "TWILIO_PHONE_NUMBER": "+15555550000",
    }
    app = create_app(load_settings(env_file=None, environ=live_env))
    assert isinstance(app.state.pipeline.deps.voice, VoiceLiveBridge)
    assert app.state.pipeline.deps.voice.live is True


def test_app_loggers_reach_a_handler_under_a_bare_server():
    """uvicorn configures only its own loggers; create_app gives the root logger a handler so the webhook evidence lines are not dropped."""
    import logging

    from app.config import load_settings
    from app.main import create_app

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers[:] = []
    root.setLevel(logging.WARNING)
    try:
        create_app(load_settings(env_file=None, environ={"APP_ENV": "development", "DATABASE_URL": "sqlite://"}))  # the factory path, as uvicorn takes it
        assert root.handlers
        assert logging.getLogger("lifeline.webhooks").getEffectiveLevel() <= logging.INFO
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
