"""Issue #109: GET /api/users/{owner_id} returns the owner's on-device record to the owner only."""

import json

import pytest
from app.config import load_settings
from app.main import create_app
from app.people import USERS_FIXTURE
from fastapi.testclient import TestClient

ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "sqlite://",
    "NEMOTRON_NANO_TAG": "nemotron-nano:4bit-test",
    "NEMOTRON_SUPER_ID": "nvidia/super-test",
    "NVIDIA_API_KEY": "test-key",
    "TWILIO_AUTH_TOKEN": "test-token",
    "DEMO_PHONE_ALLOWLIST": "+15550100001",
    "PUBLIC_BASE_URL": "https://example.test",
}
FIXTURE = json.loads(USERS_FIXTURE.read_text(encoding="utf-8"))
OWNER = FIXTURE["owner"]
CONTACT = FIXTURE["contacts"][0]


@pytest.fixture
def client():
    app = create_app(load_settings(env_file=None, environ=ENV))
    with TestClient(app) as c:
        c.get("/api/session")
        yield c


def test_owner_gets_the_record_with_the_member_id_masked(client):
    r = client.get(f"/api/users/{OWNER['id']}", params={"viewer_id": OWNER["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == OWNER["name"]
    assert body["dob"] == OWNER["dob"]
    assert body["home_address"] == OWNER["home"]["address"]
    assert body["insurance"]["carrier"] == OWNER["insurance"]["carrier"]
    assert body["insurance"]["member_id_masked"].endswith(OWNER["insurance"]["member_id"][-4:])
    assert OWNER["insurance"]["member_id"] not in r.text
    assert body["kept_on_device"] is True
    assert body["shared_fields"] == ["care_type", "budget_max", "insurance_carrier", "time_range", "needs_ride", "search_area"]


def test_contact_viewer_gets_nothing_from_the_record(client):
    # The contacts table is seeded when the owner's contacts are first resolved; a demo reset does that too.
    client.post("/api/demo/reset")
    r = client.get(f"/api/users/{OWNER['id']}", params={"viewer_id": CONTACT["id"]})
    assert r.status_code == 404
    for secret in (OWNER["dob"], OWNER["home"]["address"], OWNER["insurance"]["member_id"]):
        assert secret not in r.text


def test_unknown_owner_is_404(client):
    r = client.get("/api/users/nobody", params={"viewer_id": "nobody"})
    assert r.status_code == 404


def test_route_requires_the_session_cookie():
    app = create_app(load_settings(env_file=None, environ=ENV))
    with TestClient(app) as c:
        r = c.get(f"/api/users/{OWNER['id']}", params={"viewer_id": OWNER["id"]})
        assert r.status_code == 401
