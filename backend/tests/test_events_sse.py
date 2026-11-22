"""Issue #9: emit persists and fans out; GET /api/live sends snapshot, then events with increasing ids, heartbeats and
the anti-buffering headers; the contact never receives owner events or request.text; the poll endpoint matches."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from app import projections
from app.config import load_settings
from app.events import (
    EVENT_TYPES,
    Viewer,
    emit,
    list_events,
    project_event,
    resolve_viewer,
    visible_to,
)
from app.main import create_app
from app.models import Call, Contact, Event, Task
from app.routers import live as live_router
from app.session import COOKIE, is_valid, issue
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from sqlmodel import Session

SHARED = Path(__file__).resolve().parents[2] / "shared"
_SCHEMAS = [json.loads((SHARED / n).read_text()) for n in ("events.schema.json", "intake_request.schema.json", "decision.schema.json", "task.schema.json")]
EVENTS_VALIDATOR = Draft202012Validator(
    _SCHEMAS[0], registry=Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in _SCHEMAS]), format_checker=FormatChecker()
)


def schema_valid(event: dict) -> None:
    """Validate the flat event as the dashboard receives it (without the stream id)."""
    EVENTS_VALIDATOR.validate({k: v for k, v in event.items() if k != "id"})

RAW = "I need a dental cleaning this week, under $150. I have Delta Dental."
CHIPS = ["Dental cleaning", "Max $150", "Delta Dental", "!Processed on device"]


@pytest.fixture
def client(tmp_path):
    settings = load_settings(env_file=None, environ={"DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db"})
    app = create_app(settings)
    app.state.heartbeat_seconds = 0.05
    with TestClient(app) as c:
        assert c.get("/api/session").json() == {"ok": True}  # the dashboard's one-time call; the cookie jar keeps it
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
    assert owner_view[0]["text"] == RAW and owner_view[0]["visibility"] == "owner"
    assert "text" not in contact_view[0] and contact_view[0]["chips"] == CHIPS and contact_view[0]["visibility"] == "contact"
    for event in owner_view + contact_view:
        schema_valid(event)
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
        # #102: no-transform and identity keep the Next.js dev server and tunnels from gzip-buffering the stream
        assert resp.headers["cache-control"] == "no-cache, no-transform"
        assert resp.headers["content-encoding"] == "identity"
        assert resp.headers["x-accel-buffering"] == "no"
        messages = sse_messages(resp.iter_lines())
        snap_id, snap = next(messages)
        assert snap["type"] == "snapshot"
        assert snap_id == str(first.id)
        assert "cursor" not in snap and "last_event_id" not in snap
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
        schema_valid(ev1)
        schema_valid(ev2)


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
    assert "text" not in seen[0] and seen[0]["chips"] == CHIPS and seen[0]["visibility"] == "contact"
    assert RAW not in json.dumps(seen)
    for event in seen:
        schema_valid(event)


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
        messages = sse_messages(resp.iter_lines())  # held: dropping the iterator closes the stream under httpx2
        snap_id, snap = next(messages)
    assert snap == {"type": "snapshot", "task": None, "calls": [], "events": []} and snap_id is None


def test_subscriptions_are_released_on_disconnect(client):
    bus = client.app.state.bus
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        messages = sse_messages(resp.iter_lines())  # held: dropping the iterator closes the stream under httpx2
        next(messages)
        assert bus.subscriber_count == 1
    deadline = time.time() + 2
    while bus.subscriber_count and time.time() < deadline:
        time.sleep(0.02)
    assert bus.subscriber_count == 0


def anonymous(client) -> TestClient:
    bare = TestClient(client.app)
    bare.cookies.clear()
    return bare


def test_read_routes_require_the_dashboard_session_cookie(client):
    bare = anonymous(client)
    assert bare.get("/api/tasks/t1/events?viewer_id=mary").status_code == 401
    with bare.stream("GET", "/api/live?viewer_id=mary") as resp:
        assert resp.status_code == 401
    forged = TestClient(client.app)
    forged.cookies.set(COOKIE, "nonce.deadbeef")
    assert forged.get("/api/tasks/t1/events?viewer_id=mary").status_code == 401
    assert client.get("/api/tasks/t1/events?viewer_id=mary").status_code == 200


def test_session_route_issues_a_signed_httponly_cookie_once(client):
    bare = anonymous(client)
    first = bare.get("/api/session")
    assert first.status_code == 200 and first.json() == {"ok": True}
    set_cookie = first.headers["set-cookie"].lower()
    assert set_cookie.startswith(f"{COOKIE}=") and "httponly" in set_cookie and "samesite=lax" in set_cookie
    token = bare.cookies.get(COOKIE)
    assert is_valid(token, client.app.state.session_secret)
    assert not is_valid(token, "another-secret")
    assert "set-cookie" not in bare.get("/api/session").headers, "a valid cookie is kept, not reissued"
    assert issue("s") != issue("s")


def test_emit_during_snapshot_is_sent_once_after_it(client, monkeypatch):
    emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
    real_snapshot = live_router.snapshot

    def snapshot_then_emit(engine, viewer):
        snap = real_snapshot(engine, viewer)
        emit_to(client, "call_status", {"call_id": "a", "status": "done"}, "contact")  # lands between snapshot and send
        return snap

    monkeypatch.setattr(live_router, "snapshot", snapshot_then_emit)
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        messages = sse_messages(resp.iter_lines())
        snap_id, snap = next(messages)
        assert [e["type"] for e in snap["events"]] == ["request"]
        ev_id, ev = until(messages, lambda m: m[1]["type"] == "call_status")
        assert int(ev_id) > int(snap_id) and ev["status"] == "done"
        for _ in range(3):  # nothing but heartbeats follows: the same event is never sent twice
            assert next(messages)[1]["type"] == "heartbeat"


def test_out_of_order_notifications_still_stream_in_id_order_once(client):
    engine, bus = client.app.state.engine, client.app.state.bus
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        messages = sse_messages(resp.iter_lines())
        next(messages)
        with Session(engine) as s:
            a = Event(task_id="t1", type="call_status", payload_json=json.dumps({"call_id": "a", "status": "live"}), visibility="contact")
            b = Event(task_id="t1", type="call_status", payload_json=json.dumps({"call_id": "a", "status": "done"}), visibility="contact")
            s.add(a)
            s.add(b)
            s.commit()
            s.refresh(a)
            s.refresh(b)
            s.expunge_all()
        bus.publish(b, "mary")  # the later id is notified first
        bus.publish(a, "mary")
        got = [until(messages, lambda m: m[1]["type"] != "heartbeat") for _ in range(2)]
        assert [int(i) for i, _ in got] == [a.id, b.id]
        assert [e["status"] for _, e in got] == ["live", "done"]
        for _ in range(3):
            assert next(messages)[1]["type"] == "heartbeat"


def test_project_event_variants_are_schema_valid():
    row = Event(id=7, task_id="t1", type="request", payload_json=json.dumps({"text": RAW, "chips": CHIPS}), visibility="contact")
    owner = project_event(row, "owner")
    contact = project_event(row, "contact")
    assert owner["visibility"] == "owner" and owner["text"] == RAW
    assert contact["visibility"] == "contact" and "text" not in contact
    schema_valid(owner)
    schema_valid(contact)
    assert owner["at"].endswith("+00:00")
    assert Viewer("sarah", "contact", "mary").role == "contact"


def test_emit_between_cursor_read_and_event_list_is_left_for_the_stream(client, monkeypatch):
    """A commit that lands after the snapshot's cursor is read but before its event list is loaded must not be in the
    snapshot (its id is above the cursor) and must arrive exactly once on the stream."""
    emit_to(client, "request", {"text": RAW, "chips": CHIPS}, "contact")
    real_last_event_id = projections.last_event_id

    def cursor_then_emit(session, owner_id):
        cursor = real_last_event_id(session, owner_id)
        emit_to(client, "call_status", {"call_id": "a", "status": "hold"}, "contact")  # between the two reads
        return cursor

    monkeypatch.setattr(projections, "last_event_id", cursor_then_emit)
    with client.stream("GET", "/api/live?viewer_id=mary") as resp:
        messages = sse_messages(resp.iter_lines())
        snap_id, snap = next(messages)
        assert [e["type"] for e in snap["events"]] == ["request"], "the in-between event is not in the snapshot"
        assert all(e["id"] <= int(snap_id) for e in snap["events"])
        ev_id, ev = until(messages, lambda m: m[1]["type"] == "call_status")
        assert int(ev_id) > int(snap_id) and ev["status"] == "hold"
        for _ in range(3):
            assert next(messages)[1]["type"] == "heartbeat"


def test_publish_to_a_dead_subscriber_loop_drops_it_without_raising(client):
    import asyncio

    bus = client.app.state.bus
    loop = asyncio.new_event_loop()
    loop.close()
    from app.events import Subscription, Viewer

    dead = Subscription(viewer=Viewer("mary", "owner", "mary"), loop=loop, queue=asyncio.Queue())
    bus._subs.add(dead)
    row = emit_to(client, "task_updated", {"status": "calling"}, "contact")
    assert row.id is not None
    assert dead not in bus._subs, "a subscriber whose loop is closed is dropped, and emit still returned the committed row"


def test_contact_projection_drops_owner_sms_text(client):
    emit_to(client, "booked", {"calendar": "Appointment · Thu", "sms_user": "LifeLine: Booked ... $95 with Delta Dental."}, "contact")
    emit_to(client, "notified", {"sms_contact": "LifeLine: Thank you.", "sms_user": "LifeLine: Sarah will drive you."}, "contact")
    owner = client.get("/api/tasks/t1/events?viewer_id=mary").json()
    contact = client.get("/api/tasks/t1/events?viewer_id=sarah").json()
    assert owner[0]["sms_user"].endswith("Delta Dental.") and owner[1]["sms_user"]
    assert contact[0]["sms_user"] == "" and contact[0]["calendar"] == "Appointment · Thu"
    assert "sms_user" not in contact[1] and contact[1]["sms_contact"] == "LifeLine: Thank you."
    for event in owner + contact:
        schema_valid(event)
