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
