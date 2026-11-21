"""T1 with every adapter in mock mode: assert the full event sequence. Also T3 (nothing fits), T7 (tentative), T10 (decline),
and that the two waits resume only on the matching POST."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.adapters import Deps
from app.config import load_settings
from app.main import create_app
from fastapi.testclient import TestClient

from tests.stand_ins import DEMO_TEXT, FakeNano, FakeSuper, FakeVoice

DEMO_NOW = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
FAKE_PHONES = "+15555550100,+15555550101,+15555550111,+15555550112,+15555550113"

T1_SEQUENCE = [
    "task_updated",          # intake
    "task_updated",          # calendar
    "request",
    "task_updated",          # places
    "call_start", "call_start", "call_start",
    "task_updated",          # calling
    # call_status / transcript / call_result interleave here
    "task_updated",          # ranking
    "decision",
    "task_updated",          # awaiting_approval
    "approval_required",
    "approved",
    "task_updated",          # booking
    "booked",
    "task_updated",          # transport
    "transport_check", "transport_check",
    "task_updated",          # awaiting_contact
    "contact_request",
    "contact_reply",
    "ride_confirmed",
    "notified",
    "task_updated",          # completed
]


def make_client(monkeypatch, tmp_path, voice: FakeVoice | None = None, nano: FakeNano | None = None):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)  # the integrations mocks read the allowlist from the environment
    for var in ("VOICE_MODE", "PLACES_MODE", "CALENDAR_MODE", "SMS_MODE", "TRANSPORT_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    settings = load_settings(env_file=None, environ={"DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db", "DEMO_PHONE_ALLOWLIST": FAKE_PHONES})
    voice = voice or FakeVoice()
    deps = Deps(voice=voice, intake_model=lambda: nano or FakeNano(), rank_client=FakeSuper, now=lambda: DEMO_NOW)
    app = create_app(settings, deps=deps)
    client = TestClient(app)
    client.__enter__()
    assert client.get("/api/session").json() == {"ok": True}
    return client, voice


def wait_for(client, task_id, status, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()
        if task["status"] == status:
            return task
        if task["status"] in ("failed", "cancelled") and status not in ("failed", "cancelled"):
            raise AssertionError(f"task {task['status']}: {task.get('failure_reason')} {[e for e in events(client, task_id) if e['type']=='task_updated'][-1]}")
        time.sleep(0.02)
    raise AssertionError(f"task never reached {status}; last status {task['status']}")


def events(client, task_id, viewer="mary"):
    return client.get(f"/api/tasks/{task_id}/events?viewer_id={viewer}").json()


def start(client, text=DEMO_TEXT, key="req-1"):
    r = client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "text": text, "idempotency_key": key})
    assert r.status_code == 201, r.text
    return r.json()["task_id"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    c, voice = make_client(monkeypatch, tmp_path)
    c.voice = voice
    yield c
    c.__exit__(None, None, None)


def test_t1_standard_run_produces_the_full_event_sequence(client):
    task_id = start(client)
    task = wait_for(client, task_id, "awaiting_approval")
    assert task["decision"]["winner_call_id"] == "a" and task["chips"] == ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"]
    assert task["request_text"] == DEMO_TEXT and task["booking"] is None, "nothing booked before approval"
    assert client.voice.confirmed == []

    r = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok-1"})
    assert r.status_code == 200 and r.json()["applied"] is True
    task = wait_for(client, task_id, "awaiting_contact")
    assert task["booking"]["status"] == "confirmed" and task["booking"]["calendar_event_id"].startswith("mock-calendar-")
    assert task["transport"] == {"available": False, "reason": "UNAVAILABLE_ACCESSIBLE_RIDE", "simulated": True}
    assert client.voice.confirmed == ["a"]

    r = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "ride-1"})
    assert r.status_code == 200 and r.json()["status"] == "ride_confirmed"
    task = wait_for(client, task_id, "completed")

    seq = [e["type"] for e in events(client, task_id)]
    voice_types = {"call_status", "transcript", "call_result"}
    assert [t for t in seq if t not in voice_types] == T1_SEQUENCE
    assert seq.count("call_result") == 3 and seq.count("transcript") >= 10 and "hold" in [e.get("status") for e in events(client, task_id) if e["type"] == "call_status"]
    statuses = [e["status"] for e in events(client, task_id) if e["type"] == "task_updated"]
    assert statuses == ["intake", "calendar", "places", "calling", "ranking", "awaiting_approval", "booking", "transport", "awaiting_contact", "completed"]
    results = {e["call_id"]: e for e in events(client, task_id) if e["type"] == "call_result"}
    assert results["a"] == {**results["a"], "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True, "simulated": True}
    assert results["b"]["slotOk"] is False and results["c"]["slotOk"] is False
    decision = next(e for e in events(client, task_id) if e["type"] == "decision")
    assert decision["winner"] == "a" and decision["title"] == "Why Nemotron picked Bright Smile Dental" and len(decision["reasons"]) >= 2
    booked = next(e for e in events(client, task_id) if e["type"] == "booked")
    assert booked["calendar"].startswith("Appointment · Thu Nov 26 · 9:30–10:30 AM · 123 Main St") and "tentative" not in booked
    contact_request = next(e for e in events(client, task_id) if e["type"] == "contact_request")
    assert contact_request["contact"] == "Sarah" and "Bright Smile Dental" in contact_request["message"] and "123 Main St" in contact_request["message"]
    assert "knee" not in contact_request["message"] and "DEMO" not in contact_request["message"]
    # the contact view: same trail, never the raw text
    contact_seq = events(client, task_id, viewer="sarah")
    assert [e["type"] for e in contact_seq if e["type"] not in voice_types] == T1_SEQUENCE
    assert all("text" not in e for e in contact_seq if e["type"] == "request")
    assert DEMO_TEXT not in str(contact_seq)
    # the snapshot after the run restores the trail (T11 shape)
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        first = next(line for line in resp.iter_lines() if line.startswith("data: "))
    assert '"type": "snapshot"' in first and '"status": "completed"' in first


def test_waits_resume_only_on_the_matching_post(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    # a contact reply cannot stand in for the owner's approval, and a stranger cannot approve
    assert client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "x"}).status_code == 409
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=sarah", json={"actor_id": "sarah", "decision": "approve", "idempotency_key": "x"}).status_code == 403
    time.sleep(0.1)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
    client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"})
    wait_for(client, task_id, "awaiting_contact")
    # a second approve is answered, not re-applied; a decline keeps the task waiting (T10)
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"}).json()["applied"] is False
    r = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": False}, "idempotency_key": "no"})
    assert r.json() == {"status": "awaiting_contact", "ride": "declined"}
    time.sleep(0.1)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_contact"
    assert [e["type"] for e in events(client, task_id)][-1] == "contact_reply" and "ride_confirmed" not in [e["type"] for e in events(client, task_id)]
    assert client.voice.confirmed == ["a"], "the booking call-back ran exactly once"


def test_reject_cancels_without_booking(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    r = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "reject", "idempotency_key": "no"})
    assert r.json()["status"] == "cancelled"
    task = wait_for(client, task_id, "cancelled")
    assert task["booking"] is None and client.voice.confirmed == []
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "cancelled"


def test_t3_all_offers_over_budget_fails_honestly(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    try:
        task_id = start(client, text=DEMO_TEXT.replace("$150", "$50"))  # the regex backstop reads the budget from the words
        task = wait_for(client, task_id, "failed")
        assert task["failure_reason"] == "NO_ELIGIBLE_OFFER" and task["decision"] is None and task["booking"] is None
        last = [e for e in events(client, task_id) if e["type"] == "task_updated"][-1]
        assert "nothing was booked" in last["message"] and "$95 is over the $50 budget" in last["message"]
        assert "decision" not in [e["type"] for e in events(client, task_id)]
    finally:
        client.__exit__(None, None, None)


def test_t7_tentative_booking_creates_no_calendar_event(monkeypatch, tmp_path):
    client, _voice = make_client(monkeypatch, tmp_path, voice=FakeVoice(booking_status="tentative"))
    try:
        task_id = start(client)
        wait_for(client, task_id, "awaiting_approval")
        client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"})
        task = wait_for(client, task_id, "awaiting_contact")
        assert task["booking"]["status"] == "tentative" and task["booking"]["calendar_event_id"] is None
        booked = next(e for e in events(client, task_id) if e["type"] == "booked")
        assert booked["tentative"] is True and booked["calendar"] == "" and "call back to confirm" in booked["sms_user"]
    finally:
        client.__exit__(None, None, None)


def test_request_idempotency_and_validation(client):
    first = client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "text": DEMO_TEXT, "idempotency_key": "same"})
    again = client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "text": DEMO_TEXT, "idempotency_key": "same"})
    assert first.status_code == 201 and again.status_code == 200 and first.json() == again.json()
    assert client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "idempotency_key": "k2"}).status_code == 422
    assert client.post("/api/requests?viewer_id=mary", json={"owner_id": "nobody", "actor_id": "nobody", "text": "x", "idempotency_key": "k3"}).status_code == 404
    history = client.get("/api/tasks?viewer_id=mary&owner_id=mary&limit=5").json()
    assert [t["id"] for t in history] == [first.json()["task_id"]]
    assert client.get("/api/tasks?viewer_id=sarah&owner_id=mary").json()[0]["viewer_role"] == "contact"
    assert client.get("/api/tasks?viewer_id=other").json() == []
    wait_for(client, first.json()["task_id"], "awaiting_approval")
