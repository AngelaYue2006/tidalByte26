"""T8: a repeated POST or a re-run step creates no second SMS, booking or calendar event (receipts keyed by task + step).

The Twilio inbound webhook itself is tested with the approval module (#22); this file covers the receipts layer every
route and step share: request keys, per-route replies, the SMS, booking and calendar effects, and a restart.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from app import receipts
from app.orchestrator import Pipeline
from sqlmodel import Session, select

from integrations import google_calendar, sms_twilio
from tests.test_pipeline_mock import call_ids, events, make_client, start, wait_for


class Counting:
    """Wraps an adapter function and records every (key) it was called with."""

    def __init__(self, func):
        self.func, self.calls = func, []

    def __call__(self, *args):
        self.calls.append(args[-1])  # every adapter takes its idempotency key last
        return self.func(*args)


@pytest.fixture
def client(monkeypatch, tmp_path):
    sms, calendar = Counting(sms_twilio.send), Counting(google_calendar.create_event)
    c, voice = make_client(monkeypatch, tmp_path, sms_send=sms, create_event=calendar)
    c.voice, c.sms, c.calendar = voice, sms, calendar
    yield c
    c.__exit__(None, None, None)


def approve(client, task_id, key="ok-1"):
    return client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": key})


def offer(client, task_id, key="ride-1"):
    return client.post("/api/contacts/offers?viewer_id=sarah", json={"task_id": task_id, "contact_id": "sarah", "offer": {"can_drive": True}, "idempotency_key": key})


def receipt_steps(client, task_id) -> list[str]:
    with Session(client.app.state.engine) as session:
        return sorted(r.step for r in session.exec(select(receipts.Receipt).where(receipts.Receipt.task_id == task_id)))


def test_repeated_approve_books_once_and_writes_one_calendar_event(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    bright = call_ids(client, task_id)["Bright Smile Dental"]
    first = approve(client, task_id)
    assert first.status_code == 200 and first.json() == {"status": "approved", "applied": True}
    wait_for(client, task_id, "awaiting_contact")
    for _ in range(3):  # the dashboard retries, the SMS webhook relays the same YES: the same answer, nothing new
        again = approve(client, task_id)
        assert again.status_code == 200 and again.json() == first.json()
    later = approve(client, task_id, key="ok-2")
    assert later.status_code in (200, 409) and (later.status_code == 409 or later.json()["applied"] is False)
    assert client.voice.confirmed == [bright], "one booking call-back"
    assert client.calendar.calls == [f"{task_id}:calendar"], "one calendar insert"
    assert client.sms.calls == [f"{task_id}:approval", f"{task_id}:booked", f"{task_id}:contact_request"]
    assert [e["type"] for e in events(client, task_id)].count("approved") == 1
    assert [e["type"] for e in events(client, task_id)].count("booked") == 1
    steps = receipt_steps(client, task_id)
    assert {"booking:confirm", "calendar", "sms:approval", "sms:booked", "sms:contact_request", "reply:approve:ok-1", "request:req-1"} <= set(steps)
    assert len(steps) == len(set(steps))


def test_repeated_contact_offer_confirms_the_ride_once(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    approve(client, task_id)
    wait_for(client, task_id, "awaiting_contact")
    first = offer(client, task_id)
    assert first.status_code == 200 and first.json()["status"] == "ride_confirmed"
    wait_for(client, task_id, "completed")
    for _ in range(2):
        assert offer(client, task_id).json() == first.json()
    assert offer(client, task_id, key="ride-2").status_code == 409
    seq = [e["type"] for e in events(client, task_id)]
    assert seq.count("ride_confirmed") == 1 and seq.count("notified") == 1 and seq.count("contact_reply") == 1
    assert client.sms.calls[-2:] == [f"{task_id}:final_owner", f"{task_id}:final_contact"] and len(client.sms.calls) == len(set(client.sms.calls)) == 5
    assert client.calendar.calls == [f"{task_id}:calendar"] and len(client.voice.confirmed) == 1


def test_repeated_request_key_creates_one_task(client):
    body = {"owner_id": "mary", "actor_id": "mary", "text": "I need a dental cleaning this week, under $150, Delta Dental.", "idempotency_key": "req-dup"}
    first = client.post("/api/requests?viewer_id=mary", json=body)
    assert first.status_code == 201
    again = client.post("/api/requests?viewer_id=mary", json=body)
    assert again.status_code == 200 and again.json() == first.json()
    wait_for(client, first.json()["task_id"], "awaiting_approval")
    assert [t["id"] for t in client.get("/api/tasks?viewer_id=mary").json()] == [first.json()["task_id"]]
    assert client.sms.calls == [f"{first.json()['task_id']}:approval"]


def test_rerunning_a_step_returns_the_first_receipt(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    engine = client.app.state.engine
    produced: list[int] = []

    def produce():
        produced.append(1)
        return {"message_id": f"m{len(produced)}", "text": "hello"}

    first, repeated = receipts.once(engine, task_id, "sms:test_step", "sms", produce, external_id=lambda r: r["message_id"])
    assert (first, repeated) == ({"message_id": "m1", "text": "hello"}, False)
    second, repeated = receipts.once(engine, task_id, "sms:test_step", "sms", produce, external_id=lambda r: r["message_id"])
    assert (second, repeated) == (first, True) and produced == [1], "the second run never reached the adapter"
    # a race on a fresh step: whoever loses the INSERT gets the winner's payload, and exactly one receipt is kept
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: receipts.once(engine, task_id, "sms:race", "sms", lambda: {"message_id": f"race{i}"})[0], range(6)))
    assert len({r["message_id"] for r in results}) == 1
    assert receipt_steps(client, task_id).count("sms:race") == 1
    # a step that fails leaves no receipt, so a retry runs it again
    with pytest.raises(RuntimeError):
        receipts.once(engine, task_id, "sms:boom", "sms", lambda: (_ for _ in ()).throw(RuntimeError("carrier down")))
    assert "sms:boom" not in receipt_steps(client, task_id)


def test_replies_and_request_keys_survive_a_restart(client):
    task_id = start(client, key="req-restart")
    wait_for(client, task_id, "awaiting_approval")
    approve(client, task_id, key="ok-restart")
    wait_for(client, task_id, "awaiting_contact")
    old = client.app.state.pipeline
    fresh = Pipeline(old.deps, old.engine, old.bus)  # the process restarted: nothing in memory
    assert fresh.replay("approve", task_id, "ok-restart") == {"status": "approved", "applied": True}
    assert fresh.replay("approve", task_id, "never-seen") is None
    assert fresh.task_for_request_key("req-restart") == task_id and fresh.task_for_request_key("other") is None
