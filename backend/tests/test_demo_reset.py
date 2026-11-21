"""T12: two runs, then POST /api/demo/reset clears every table and reseeds the fixtures with two past runs; the
history list is newest first and viewer-scoped; reset is refused outside APP_ENV=development."""

from __future__ import annotations

import json
import threading

import pytest
from app import seed
from app.config import load_settings
from app.events import RESET_SIGNAL, EventBus, Viewer
from app.models import TABLES
from sqlalchemy import text
from sqlmodel import Session

from tests.stand_ins import DEMO_TEXT
from tests.test_pipeline_mock import (
    EVENTS_VALIDATOR,
    TASK_VALIDATOR,
    events,
    make_client,
    start,
    wait_for,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    c, voice = make_client(monkeypatch, tmp_path)
    c.voice = voice
    yield c
    c.__exit__(None, None, None)


def complete_run(client, key) -> str:
    task_id = start(client, key=key)
    wait_for(client, task_id, "awaiting_approval")
    client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": f"ok-{key}"})
    wait_for(client, task_id, "awaiting_contact")
    client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": f"ride-{key}"})
    wait_for(client, task_id, "completed")
    return task_id


def row_counts(engine) -> dict[str, int]:
    with Session(engine) as session:
        return {table: session.exec(text(f"SELECT count(*) FROM {table}")).one()[0] for table in TABLES}


def test_t12_two_runs_then_reset_clears_and_reseeds(client):
    first, second = complete_run(client, "run-1"), complete_run(client, "run-2")
    history = client.get("/api/tasks?viewer_id=mary&owner_id=mary").json()
    assert [t["id"] for t in history] == [second, first], "newest first"
    assert all(t["status"] == "completed" and t["booking"]["clinic"] == "Bright Smile Dental" and t["booking"]["price"] == "$95" for t in history)
    assert all(t["transport"]["reason"] == "UNAVAILABLE_ACCESSIBLE_RIDE" for t in history)
    before = row_counts(client.app.state.engine)
    assert before["tasks"] == 2 and before["receipts"] >= 14 and before["events"] > 40 and before["calls"] == 6

    r = client.post("/api/demo/reset")
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] == before and r.json()["seeded"] == {"tasks": 2, "contacts": 1} and r.json()["stopped"] == 0
    after = row_counts(client.app.state.engine)
    assert after["receipts"] == 0 and after["turns"] == 0 and after["contacts"] == 1 and after["tasks"] == 2 and after["calls"] == 6
    assert client.get(f"/api/tasks/{first}?viewer_id=mary").status_code == 404, "the old runs are gone"

    seeded = client.get("/api/tasks?viewer_id=mary").json()
    assert [t["status"] for t in seeded] == ["completed", "completed"] and seeded[0]["created_at"] > seeded[1]["created_at"]
    assert [t["booking"]["clinic"] for t in seeded] == ["Bright Smile Dental", "Smile Co."]
    assert seeded[0]["intake"]["needs_ride"] is True and seeded[1]["intake"]["needs_ride"] is False
    for task in seeded:
        TASK_VALIDATOR.validate(task)
        assert task["chips"][-1] == "!Processed on device" and task["decision"]["winner_call_id"].startswith(task["id"][:8])
        for event in events(client, task["id"]):
            EVENTS_VALIDATOR.validate({k: v for k, v in event.items() if k != "id"})
            assert event.get("simulated", True) is True or event["type"] in ("task_updated", "request", "decision", "approval_required", "approved", "contact_request", "contact_reply", "ride_confirmed")
    with_ride = [e["type"] for e in events(client, seeded[0]["id"])]
    assert with_ride[-3:] == ["ride_confirmed", "notified", "task_updated"] and with_ride.count("call_result") == 3
    assert "ride_confirmed" not in [e["type"] for e in events(client, seeded[1]["id"])]

    # the demo runs again from the reseeded state
    third = complete_run(client, "run-3")
    assert client.get("/api/tasks?viewer_id=mary").json()[0]["id"] == third
    assert client.post("/api/demo/reset").json()["cleared"]["tasks"] == 3


def test_history_is_viewer_scoped(client):
    client.post("/api/demo/reset")
    owner_view = client.get("/api/tasks?viewer_id=mary").json()
    contact_view = client.get("/api/tasks?viewer_id=sarah&owner_id=mary").json()
    assert [t["id"] for t in contact_view] == [t["id"] for t in owner_view]
    assert all(t["request_text"] for t in owner_view) and all(not t.get("request_text") for t in contact_view)
    for task in contact_view:
        trail = events(client, task["id"], viewer="sarah")
        assert all("text" not in e for e in trail if e["type"] == "request") and DEMO_TEXT not in json.dumps(trail)
        TASK_VALIDATOR.validate(task)
    assert client.get("/api/tasks?viewer_id=sarah&owner_id=someone-else").json() == []
    assert client.get("/api/tasks?viewer_id=mary&limit=1").json()[0]["id"] == owner_view[0]["id"]


def test_reset_stops_a_running_pipeline_and_frees_its_wait(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    pipeline = client.app.state.pipeline
    assert pipeline.waiting(task_id)
    r = client.post("/api/demo/reset")
    assert r.json()["stopped"] == 1 and not pipeline.waiting(task_id)
    assert client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "late"}).status_code == 404
    assert client.voice.confirmed == []


def test_reset_is_refused_outside_development(monkeypatch, tmp_path):
    c, _ = make_client(monkeypatch, tmp_path, environ={"APP_ENV": "staging", "DASHBOARD_SESSION_SECRET": "x" * 32})
    try:
        assert c.post("/api/demo/reset").status_code == 403
        assert c.get("/api/tasks?viewer_id=mary").json() == [], "nothing seeded"
    finally:
        c.__exit__(None, None, None)


def test_seed_is_idempotent_and_the_stream_is_told_to_start_over(tmp_path):
    settings = load_settings(env_file=None, environ={"DATABASE_URL": f"sqlite:///{tmp_path}/seed.db"})
    from app.db import init_db, make_engine

    engine = make_engine(settings.database_url)
    init_db(engine)
    assert seed.seed(engine) == {"tasks": 2, "contacts": 1}
    assert seed.seed(engine) == {"tasks": 0, "contacts": 1}, "a second seed adds nothing"
    bus = EventBus()
    told: list[int] = []
    import asyncio

    async def subscriber():
        sub = bus.subscribe(Viewer(id="mary", owner_id="mary", role="owner"))
        ready.set()
        told.append(await asyncio.wait_for(sub.queue.get(), 2))

    ready = threading.Event()
    thread = threading.Thread(target=lambda: asyncio.run(subscriber()))
    thread.start()
    ready.wait(2)
    assert bus.publish_reset() == 1
    thread.join(2)
    assert told == [RESET_SIGNAL]
