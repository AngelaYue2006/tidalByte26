"""T1 with every adapter in mock mode: assert the full event sequence. Also T3 (nothing fits), T7 (tentative), T10 (decline),
and that the two waits resume only on the matching POST."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from app.adapters import Deps, VoiceMockBridge
from app.config import load_settings
from app.main import create_app
from app.orchestrator import booking_record
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from integrations.types import Booking
from tests.stand_ins import DEMO_TEXT, FakeNano, FakeSuper, instant

SHARED = Path(__file__).resolve().parents[2] / "shared"
_SCHEMAS = [json.loads((SHARED / n).read_text()) for n in ("events.schema.json", "intake_request.schema.json", "decision.schema.json", "task.schema.json")]
_REGISTRY = Registry().with_resources([(sch["$id"], Resource.from_contents(sch)) for sch in _SCHEMAS])
TASK_VALIDATOR = Draft202012Validator(_SCHEMAS[3], registry=_REGISTRY, format_checker=FormatChecker())
EVENTS_VALIDATOR = Draft202012Validator(_SCHEMAS[0], registry=_REGISTRY, format_checker=FormatChecker())

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


class CountingVoice(VoiceMockBridge):
    """The default voice path with an instant clock, counting the booking call-backs."""

    def __init__(self, booking_status: str | None = None) -> None:
        super().__init__(sleep=instant)
        self.confirmed: list[str] = []
        self.booking_status = booking_status

    def confirm_booking(self, spec, slot):
        self.confirmed.append(spec.call_id)
        confirmation = super().confirm_booking(spec, slot)
        if self.booking_status:
            ref = confirmation.confirmation_ref if self.booking_status == "confirmed" else None
            confirmation = confirmation.model_copy(update={"status": self.booking_status, "confirmation_ref": ref})
        return confirmation


def make_client(monkeypatch, tmp_path, voice=None, nano: FakeNano | None = None):
    """The app with the default wiring (`Deps()`), only Nano and Super replaced by stand-ins and the clock pinned."""
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)  # the integrations mocks read the allowlist from the environment
    for var in ("VOICE_MODE", "PLACES_MODE", "CALENDAR_MODE", "SMS_MODE", "TRANSPORT_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    settings = load_settings(env_file=None, environ={"DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db", "DEMO_PHONE_ALLOWLIST": FAKE_PHONES})
    voice = voice or CountingVoice()
    deps = Deps(voice=voice, intake_model=lambda: nano or FakeNano(), rank_client=FakeSuper, now=lambda: DEMO_NOW)
    app = create_app(settings, deps=deps)
    client = TestClient(app)
    client.__enter__()
    assert client.get("/api/session").json() == {"ok": True}
    return client, voice


def call_ids(client, task_id) -> dict[str, str]:
    """clinic name -> task-unique call id, from the call_start events."""
    return {e["clinic"]: e["call_id"] for e in events(client, task_id) if e["type"] == "call_start"}


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
    ids = call_ids(client, task_id)
    bright = ids["Bright Smile Dental"]
    assert bright.startswith(task_id[:8]) and len(set(ids.values())) == 3
    assert task["decision"]["winner_call_id"] == bright and task["chips"] == ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"]
    assert task["request_text"] == DEMO_TEXT and task["booking"] is None, "nothing booked before approval"
    assert client.voice.confirmed == []
    TASK_VALIDATOR.validate(task)

    r = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok-1"})
    assert r.status_code == 200 and r.json()["applied"] is True
    task = wait_for(client, task_id, "awaiting_contact")
    assert task["booking"]["status"] == "confirmed" and task["booking"]["calendar_event_id"].startswith("mock-calendar-")
    assert set(task["booking"]) == {"clinic", "slot_start", "slot_end", "price", "status", "confirmation_ref", "calendar_event_id"}
    assert task["transport"] == {"available": False, "reason": "UNAVAILABLE_ACCESSIBLE_RIDE", "simulated": True}
    assert client.voice.confirmed == [bright]
    TASK_VALIDATOR.validate(task)

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
    assert results[bright] == {**results[bright], "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True, "simulated": True}
    assert results[ids["Smile Co."]]["slotOk"] is False and results[ids["Oak Dental"]]["slotOk"] is False
    decision = next(e for e in events(client, task_id) if e["type"] == "decision")
    assert decision["winner"] == bright and decision["title"] == "Why Nemotron picked Bright Smile Dental" and len(decision["reasons"]) >= 2
    for event in events(client, task_id):
        EVENTS_VALIDATOR.validate({k: v for k, v in event.items() if k != "id"})
    booked = next(e for e in events(client, task_id) if e["type"] == "booked")
    assert booked["calendar"].startswith("Appointment · Thu Nov 26 · 9:30–10:30 AM · 123 Main St") and "tentative" not in booked
    contact_request = next(e for e in events(client, task_id) if e["type"] == "contact_request")
    assert contact_request["contact"] == "Sarah" and "Bright Smile Dental" in contact_request["message"] and "123 Main St" in contact_request["message"]
    assert "knee" not in contact_request["message"] and "DEMO" not in contact_request["message"]
    # the contact view: same trail, never the raw text, never the owner's SMS text (price and insurance)
    contact_seq = events(client, task_id, viewer="sarah")
    assert [e["type"] for e in contact_seq if e["type"] not in voice_types] == T1_SEQUENCE
    assert all("text" not in e for e in contact_seq if e["type"] == "request")
    assert DEMO_TEXT not in str(contact_seq)
    owner_booked = next(e for e in events(client, task_id) if e["type"] == "booked")
    contact_booked = next(e for e in contact_seq if e["type"] == "booked")
    assert "$95" in owner_booked["sms_user"] and "Delta" in owner_booked["sms_user"]
    assert contact_booked["sms_user"] == "" and contact_booked["calendar"] == owner_booked["calendar"]
    owner_notified = next(e for e in events(client, task_id) if e["type"] == "notified")
    contact_notified = next(e for e in contact_seq if e["type"] == "notified")
    assert owner_notified["sms_user"] and "sms_user" not in contact_notified and contact_notified["sms_contact"] == owner_notified["sms_contact"]
    assert "$95" not in json.dumps(contact_seq) or all("$95" not in json.dumps({k: v for k, v in e.items() if k.startswith("sms")}) for e in contact_seq)
    for event in contact_seq:
        EVENTS_VALIDATOR.validate({k: v for k, v in event.items() if k != "id"})
    # the snapshot after the run restores the trail (T11 shape) and every representation uses the same call ids
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        first = next(line for line in resp.iter_lines() if line.startswith("data: "))
    snap = json.loads(first[6:])
    assert snap["type"] == "snapshot" and snap["task"]["status"] == "completed"
    TASK_VALIDATOR.validate(snap["task"])
    snapshot_ids = {c["call_id"] for c in snap["calls"]}
    assert snapshot_ids == set(ids.values()) == {e["call_id"] for e in snap["events"] if e["type"] == "call_start"}
    assert snap["task"]["decision"]["winner_call_id"] in snapshot_ids
    assert {c["call_id"]: c["status"] for c in snap["calls"]} == dict.fromkeys(ids.values(), "done")
    assert next(c for c in snap["calls"] if c["call_id"] == bright)["result"] == {"price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True}


def test_waits_resume_only_on_the_matching_post(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    # a contact reply cannot stand in for the owner's approval, and a stranger cannot approve
    assert client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "x"}).status_code == 409
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=sarah", json={"actor_id": "sarah", "decision": "approve", "idempotency_key": "x"}).status_code == 403
    time.sleep(0.1)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
    first = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"}).json()
    replay = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"}).json()
    assert first == replay == {"status": "approved", "applied": True}, "the same key replays the same answer"
    wait_for(client, task_id, "awaiting_contact")
    assert [e["type"] for e in events(client, task_id)].count("approved") == 1
    # a second approve with a new key is answered, not re-applied; a decline keeps the task waiting (T10)
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok-2"}).json()["applied"] is False
    r = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": False}, "idempotency_key": "no"})
    assert r.json() == {"status": "awaiting_contact", "ride": "declined"}
    time.sleep(0.1)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_contact"
    assert [e["type"] for e in events(client, task_id)][-1] == "contact_reply" and "ride_confirmed" not in [e["type"] for e in events(client, task_id)]
    assert client.voice.confirmed == [call_ids(client, task_id)["Bright Smile Dental"]], "the booking call-back ran exactly once"
    # the same declined key again: same answer, no second reply; a new key is a new reply
    before = len(events(client, task_id))
    assert client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": False}, "idempotency_key": "no"}).json() == {"status": "awaiting_contact", "ride": "declined"}
    assert len(events(client, task_id)) == before
    client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": False}, "idempotency_key": "no-2"})
    assert len(events(client, task_id)) == before + 1
    # an offer confirms once: the same key replays, a second offer with a new key is refused, one ride_confirmed in total
    first = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "yes"}).json()
    again = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "yes"}).json()
    other = client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "yes-2"})
    assert first == again and first["status"] == "ride_confirmed" and other.status_code == 409
    wait_for(client, task_id, "completed")
    assert [e["type"] for e in events(client, task_id)].count("ride_confirmed") == 1


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
    client, _voice = make_client(monkeypatch, tmp_path, voice=CountingVoice(booking_status="tentative"))
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


def test_booking_record_projects_only_the_documented_keys():
    class BookingWithAddress(Booking):  # the shape #70 gives the adapter type
        address: str | None = None

    tz = ZoneInfo("America/Chicago")
    booking = BookingWithAddress(clinic="Bright Smile Dental", address="123 Main St, Chicago, IL 60601", slot_start=datetime(2026, 11, 26, 9, 30, tzinfo=tz),
                                 slot_end=datetime(2026, 11, 26, 10, 30, tzinfo=tz), price="$95", status="confirmed")
    record = booking_record(booking)
    assert set(record) == {"clinic", "slot_start", "slot_end", "price", "status", "confirmation_ref", "calendar_event_id"}
    assert "address" not in record and record["calendar_event_id"] is None
    task_with_it = {"id": "t", "owner_id": "mary", "status": "booking", "viewer_role": "owner", "intake": None, "chips": [], "windows": [], "calls": [],
                    "decision": None, "booking": record, "transport": None, "created_at": "2026-11-21T15:00:00+00:00", "updated_at": "2026-11-21T15:00:00+00:00"}
    TASK_VALIDATOR.validate(task_with_it)


def test_default_wiring_replays_the_fixture_without_the_simulator(monkeypatch):
    """Deps() as the app builds it: the voice bridge falls back to the backend replayer when integrations.voice_mock has no API."""
    import asyncio

    from app.voice_replay import FixtureReplay

    from integrations import voice_mock
    from integrations.google_places import find_clinics
    from integrations.types import CallSpec, IntakeRequest, Window

    for name in ("callbacks", "confirm_booking"):
        monkeypatch.delattr(voice_mock, name, raising=False)
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)
    assert isinstance(Deps().voice, VoiceMockBridge)
    bridge = VoiceMockBridge(sleep=instant)
    window = Window(start=DEMO_NOW.replace(hour=0), end=DEMO_NOW.replace(day=29, hour=23))
    request = IntakeRequest(care_type="dental cleaning", budget_max=150, insurance_carrier="Delta Dental", time_range=window, needs_ride=True, search_area="near home")
    specs = [CallSpec(clinic=c, request=request, windows=[window], call_id=f"t-{i}") for i, c in enumerate(find_clinics("dental cleaning", "near home", 3))]
    seen: list[dict] = []
    offers = asyncio.run(bridge.call_clinics(specs, seen.append))
    assert [o.price for o in offers] == [95, 120, 140] and all(e["simulated"] for e in seen)
    assert sum(e["type"] == "call_result" for e in seen) == 3 and any(e.get("status") == "hold" for e in seen)
    confirmation = bridge.confirm_booking(specs[0], {"slot_start": offers[0].slot_start.isoformat()})
    assert confirmation.status == "confirmed" and confirmation.simulated
    assert FixtureReplay(instant).confirm_booking(specs[2], {"slot_start": offers[2].slot_start.isoformat()}).status == "tentative"


def _failing_once(module, name, monkeypatch):
    """Replace module.name with a function that raises on its first call and delegates afterwards."""
    real = getattr(module, name)
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected write failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, flaky)
    return calls


def test_failed_approval_write_releases_the_wait_for_a_retry(client, monkeypatch):
    from app.routers import approvals

    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    before = events(client, task_id)
    _failing_once(approvals, "emit_many", monkeypatch)
    with pytest.raises(RuntimeError, match="injected"):
        client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "k1"})
    assert events(client, task_id) == before, "nothing half-written"
    assert client.app.state.pipeline.waiting(task_id), "the wait is open again"
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
    retry = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "k1"})
    assert retry.status_code == 200 and retry.json() == {"status": "approved", "applied": True}
    wait_for(client, task_id, "awaiting_contact")
    assert [e["type"] for e in events(client, task_id)].count("approved") == 1


def test_failed_ride_write_leaves_no_partial_reply_and_allows_retry(client, monkeypatch):
    from app.routers import contacts

    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"})
    wait_for(client, task_id, "awaiting_contact")
    before = events(client, task_id)
    _failing_once(contacts, "emit_many", monkeypatch)
    offer = {"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "ride"}
    with pytest.raises(RuntimeError, match="injected"):
        client.post("/api/contacts/offers?viewer_id=sarah", json=offer)
    after = events(client, task_id)
    assert after == before, "neither contact_reply nor ride_confirmed was written"
    assert client.app.state.pipeline.waiting(task_id)
    retry = client.post("/api/contacts/offers?viewer_id=sarah", json=offer)
    assert retry.status_code == 200 and retry.json()["status"] == "ride_confirmed"
    wait_for(client, task_id, "completed")
    types = [e["type"] for e in events(client, task_id)]
    assert types.count("contact_reply") == 1 and types.count("ride_confirmed") == 1
    assert types.index("contact_reply") + 1 == types.index("ride_confirmed"), "the reply and the confirmation are adjacent: one transaction"


def test_failed_reject_write_keeps_the_task_awaiting_and_retry_cancels(client, monkeypatch):
    from app.routers import approvals

    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    _failing_once(approvals, "emit_many", monkeypatch)
    with pytest.raises(RuntimeError):
        client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "reject", "idempotency_key": "r"})
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval", "the status change rolled back with the event"
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "reject", "idempotency_key": "r"}).json()["status"] == "cancelled"
    wait_for(client, task_id, "cancelled")


def test_publish_failure_after_commit_keeps_the_event_and_never_duplicates(client, monkeypatch):
    """Fan-out is not persistence: a publish error after the commit leaves the approval applied and the retry a replay."""
    from app import events as events_module

    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    real_publish = events_module.EventBus.publish
    calls = {"n": 0}

    def flaky_publish(self, row, owner_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("subscriber loop closed")
        return real_publish(self, row, owner_id)

    monkeypatch.setattr(events_module.EventBus, "publish", flaky_publish)
    first = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "p"})
    assert first.status_code == 200 and first.json() == {"status": "approved", "applied": True}, "committed events are authoritative"
    again = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "p"})
    assert again.json() == first.json()
    wait_for(client, task_id, "awaiting_contact")
    assert [e["type"] for e in events(client, task_id)].count("approved") == 1
    # the stream still carries the committed approval: the heartbeat tick reads past the cursor
    monkeypatch.setattr(events_module.EventBus, "publish", lambda self, row, owner_id: (_ for _ in ()).throw(RuntimeError("down")))
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        lines = resp.iter_lines()
        snapshot_line = next(line for line in lines if line.startswith("data: "))
        assert "approved" in snapshot_line
        client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "r"})
        seen = []
        for line in lines:
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                if payload["type"] != "heartbeat":
                    seen.append(payload["type"])
                if "ride_confirmed" in seen:
                    break
    assert "contact_reply" in seen and "ride_confirmed" in seen, "delivered with no publish at all, via the catch-up read"


def test_refused_sms_is_reported_to_the_owner_and_never_shown_as_sent(monkeypatch, tmp_path):
    from integrations import sms_twilio

    real_send = sms_twilio.send

    def refuse_owner(to, text, key):
        if to == "+15555550100":
            raise RuntimeError("UNVERIFIED_SENDER: phone is not on the demo allowlist")
        return real_send(to, text, key)

    client, _voice = make_client(monkeypatch, tmp_path)
    client.app.state.pipeline.deps.sms_send = refuse_owner
    try:
        task_id = start(client)
        wait_for(client, task_id, "awaiting_approval")
        client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"})
        task = wait_for(client, task_id, "awaiting_contact")
        assert task["booking"]["status"] == "confirmed" and task["booking"]["calendar_event_id"], "the calendar receipt stands on its own"
        booked = next(e for e in events(client, task_id) if e["type"] == "booked")
        assert booked["sms_user"] == "" and booked["calendar"].startswith("Appointment"), "no text claimed as sent"
        failures = [e for e in events(client, task_id) if e["type"] == "task_updated" and e.get("reason") == "SMS_NOT_SENT"]
        assert len(failures) >= 2 and all(e["visibility"] == "owner" and "allowlist" in e["message"] for e in failures)
        assert not [e for e in events(client, task_id, viewer="sarah") if e.get("reason") == "SMS_NOT_SENT"]
        client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": "r"})
        wait_for(client, task_id, "completed")
        notified = next(e for e in events(client, task_id) if e["type"] == "notified")
        assert notified["sms_user"] == "" and notified["sms_contact"].startswith("LifeLine:"), "the contact's receipt is shown, the owner's refusal is not faked"
    finally:
        client.__exit__(None, None, None)
