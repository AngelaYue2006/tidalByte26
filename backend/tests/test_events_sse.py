"""Issue #9: emit persists and fans out; GET /api/live sends snapshot, then events with increasing ids, heartbeats and
the anti-buffering headers; the contact never receives owner events or request.text; the poll endpoint matches."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

import pytest
from app.config import load_settings
from app.events import EVENT_TYPES, emit, list_events, resolve_viewer, visible_to
from app.main import create_app
from app.models import Call, Contact, Task
from fastapi.testclient import TestClient
from sqlmodel import Session

RAW = "I need a dental cleaning this week, under $150. I have Delta Dental."
CHIPS = ["Dental cleaning", "Max $150", "Delta Dental", "!Processed on device"]


@pytest.fixture
def client(tmp_path):
    settings = load_settings(env_file=None, environ={"DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db"})
    app = create_app(settings)
    app.state.heartbeat_seconds = 0.05
    with TestClient(app) as c:
        with Session(app.state.engine) as s:
            s.add(Task(id="t1", owner_id="mary", status="calling"))
            s.add(Contact(id="sarah", owner_id="mary", name="Sarah Johnson", phone_e164="+15555550101", relationship="daughter"))
            s.add(Contact(id="other", owner_id="someone_else", name="Other", phone_e164="+15555550199", relationship="friend"))
            s.add(Call(id="a", task_id="t1", clinic_name="Bright Smile Dental", clinic_phone="+15555550111", distance_mi=1.2, status="live"))
            s.commit()
        yield c


def emit_to(client, type, payload, visibility="owner", task_id="t1"):
    return emit(client.app.state.engine, client.app.state.bus, task_id, type, payload, visibility)


def sse_messages(lines: Iterator[str]) -> Iterator[tuple[str | None, dict]]:
    """Yield (id, data) per SSE message from an iter_lines() stream."""
    event_id, data = None, None
    for line in lines:
        if line == "":
            if data is not None:
                yield event_id, json.loads(data)
            event_id, data = None, None
        elif line.startswith("id: "):
            event_id = line[4:]
        elif line.startswith("data: "):
            data = line[6:]


def until(messages, predicate, limit=200):
    for _ in range(limit):
        msg = next(messages)
        if predicate(msg):
            return msg
    raise AssertionError("message not seen")


def test_emit_persists_with_visibility_and_lists_by_role(client):
    emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
    emit_to(client, "call_status", {"call_id": "a", "status": "live"}, "contact")
    emit_to(client, "task_updated", {"status": "calling"}, "owner")
    emit_to(client, "transcript", {"call_id": "a", "speaker": "agent", "text": "internal note"}, "internal")
    with Session(client.app.state.engine) as s:
        owner_view = list_events(s, "t1", resolve_viewer(s, "mary"))
        contact_view = list_events(s, "t1", resolve_viewer(s, "sarah"))
    assert [e["type"] for e in owner_view] == ["request", "call_status", "task_updated"]
    assert [e["type"] for e in contact_view] == ["request", "call_status"]
    assert owner_view[0]["text"] == RAW
    assert "text" not in contact_view[0] and contact_view[0]["chips"] == CHIPS
    ids = [e["id"] for e in owner_view]
    assert ids == sorted(ids) and len(set(ids)) == 3
    assert all(e["task_id"] == "t1" and e["at"] and e["visibility"] in {"owner", "contact"} for e in owner_view)


def test_emit_rejects_unknown_type_visibility_and_task(client):
    with pytest.raises(ValueError, match="unknown event type"):
        emit_to(client, "snapshot", {})
    with pytest.raises(ValueError, match="unknown visibility"):
        emit_to(client, "task_updated", {"status": "calling"}, "everyone")
    with pytest.raises(LookupError):
        emit_to(client, "task_updated", {"status": "calling"}, task_id="missing")
    assert "snapshot" not in EVENT_TYPES and "heartbeat" not in EVENT_TYPES


def test_visibility_matrix():
    assert visible_to("owner", "owner") and visible_to("owner", "contact") and not visible_to("owner", "internal")
    assert not visible_to("contact", "owner") and visible_to("contact", "contact") and not visible_to("contact", "internal")


def test_live_sends_snapshot_then_events_with_increasing_ids_and_sse_headers(client):
    first = emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        messages = sse_messages(resp.iter_lines())
        snap_id, snap = next(messages)
        assert snap["type"] == "snapshot"
        assert snap_id == str(first.id)
        assert snap["task"]["id"] == "t1" and snap["task"]["viewer_role"] == "owner"
        assert snap["task"]["request_text"] == RAW and snap["task"]["chips"] == CHIPS
        assert snap["calls"][0] == {"call_id": "a", "clinic": "Bright Smile Dental", "meta": "1.2 mi", "status": "live", "result": None}
        assert [e["type"] for e in snap["events"]] == ["request"]

        def later():
            time.sleep(0.05)
            emit_to(client, "call_status", {"call_id": "a", "status": "done"}, "contact")
            emit_to(client, "task_updated", {"status": "ranking"}, "owner")

        threading.Thread(target=later).start()
        ev1_id, ev1 = until(messages, lambda m: m[1]["type"] == "call_status")
        ev2_id, ev2 = until(messages, lambda m: m[1]["type"] == "task_updated")
        assert int(ev1_id) > first.id and int(ev2_id) > int(ev1_id)
        assert ev1["status"] == "done" and ev2["status"] == "ranking"


def test_live_heartbeat_arrives_without_events(client):
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        messages = sse_messages(resp.iter_lines())
        _, snap = next(messages)
        assert snap["type"] == "snapshot" and snap["task"]["id"] == "t1" and snap["events"] == []
        hb_id, hb = until(messages, lambda m: m[1]["type"] == "heartbeat", limit=5)
        assert hb == {"type": "heartbeat"} and hb_id is None


def test_contact_stream_never_carries_owner_events_or_request_text(client):
    emit_to(client, "task_updated", {"status": "intake"}, "owner")
    with client.stream("GET", "/api/live?viewer_id=sarah") as resp:
        messages = sse_messages(resp.iter_lines())
        _, snap = next(messages)
        assert snap["task"]["viewer_role"] == "contact"
        assert "request_text" not in snap["task"]
        assert snap["events"] == []

        def later():
            time.sleep(0.05)
            emit_to(client, "approved", {"by": "mary", "via": "dashboard"}, "owner")
            emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
            emit_to(client, "contact_request", {"contact": "Sarah", "message": "Can you drive Mary on Thu?"}, "contact")

        threading.Thread(target=later).start()
        seen = [until(messages, lambda m: m[1]["type"] != "heartbeat")[1] for _ in range(2)]
    assert [e["type"] for e in seen] == ["request", "contact_request"]
    assert "text" not in seen[0] and seen[0]["chips"] == CHIPS
    assert RAW not in json.dumps(seen)


def test_events_endpoint_matches_the_stream_filter_and_scopes_by_viewer(client):
    emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
    emit_to(client, "approved", {"by": "mary", "via": "dashboard"}, "owner")
    owner = client.get("/api/tasks/t1/events?viewer_id=mary").json()
    contact = client.get("/api/tasks/t1/events?viewer_id=sarah").json()
    assert [e["type"] for e in owner] == ["request", "approved"]
    assert [e["type"] for e in contact] == ["request"]
    assert owner[0]["text"] == RAW and "text" not in contact[0]
    assert client.get("/api/tasks/t1/events?viewer_id=other").status_code == 404
    assert client.get("/api/tasks/nope/events?viewer_id=mary").status_code == 404
    assert client.get("/api/tasks/t1/events").status_code == 422


def test_snapshot_for_a_viewer_with_no_task(client):
    with client.stream("GET", "/api/live?viewer_id=nobody") as resp:
        snap_id, snap = next(sse_messages(resp.iter_lines()))
    assert snap == {"type": "snapshot", "task": None, "calls": [], "events": []} and snap_id is None


def test_subscriptions_are_released_on_disconnect(client):
    bus = client.app.state.bus
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        next(sse_messages(resp.iter_lines()))
        assert bus.subscriber_count == 1
    deadline = time.time() + 2
    while bus.subscriber_count and time.time() < deadline:
        time.sleep(0.02)
    assert bus.subscriber_count == 0
