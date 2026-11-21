"""Issue #21: the ElevenLabs post-call webhook is signature-checked, matched to a call, turned into call_result and
call_status from structured fields (Super filling gaps from the transcript), and a repeated webhook is a no-op (T8)."""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app import call_results
from app.call_results import Window, parse_insured, parse_price, parse_slot, slot_ok
from app.config import load_settings
from app.db import session_scope
from app.main import create_app
from app.models import Call, Event, Task
from app.nemotron.call_summary import SummaryError, summarize_call
from app.routers.webhooks import sign, verify_signature
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import select

WEBHOOK_SECRET = "webhook-canary-0123456789abcdef"
ENV = {"APP_ENV": "development", "DATABASE_URL": "sqlite://", "ELEVENLABS_WEBHOOK_SECRET": WEBHOOK_SECRET, "APP_TIMEZONE": "America/Chicago"}
CHI = ZoneInfo("America/Chicago")
CALL_DATE = datetime(2026, 11, 21, 15, 0, tzinfo=CHI)  # Saturday
WINDOWS = [
    {"start": "2026-11-24T13:00:00-06:00", "end": "2026-11-24T17:00:00-06:00"},
    {"start": "2026-11-26T08:00:00-06:00", "end": "2026-11-26T12:00:00-06:00"},
]
TRANSCRIPT = [
    {"role": "agent", "message": "Hi, I'm an AI assistant calling for a patient. Do you take Delta Dental?", "time_in_call_secs": 1},
    {"role": "user", "message": "Yes, we do. A cleaning is $95 with Delta.", "time_in_call_secs": 4},
    {"role": "agent", "message": "Anything Thursday morning?", "time_in_call_secs": 6},
    {"role": "user", "message": "Thursday at 9:30 is open.", "time_in_call_secs": 9},
]


def payload(collection=None, *, conversation_id="conv-a", call_id="call-a", transcript=TRANSCRIPT, kind="post_call_transcription"):
    collection = {"price": {"value": "$95", "rationale": "said $95"}, "slot": "Thu 9:30", "insured": "yes"} if collection is None else collection
    data = {
        "agent_id": "agent-x", "conversation_id": conversation_id, "status": "done",
        "transcript": transcript,
        "analysis": {"data_collection_results": collection, "call_successful": "success"},
        "conversation_initiation_client_data": {"dynamic_variables": {"call_id": call_id}},
    }
    return {"type": kind, "event_timestamp": int(CALL_DATE.timestamp()), "data": data}


class FakeSuper:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, *, previous=None):
        self.calls.append({"system": system, "user": user, "previous": previous})
        return self.replies.pop(0)


GOOD_SUMMARY = json.dumps({"price_usd": 95, "insured": True, "slot_start": "2026-11-26T09:30:00-06:00",
                           "slot_end": "2026-11-26T10:30:00-06:00", "slot_label": "Thu 9:30"})


@pytest.fixture
def app():
    app = create_app(load_settings(env_file=None, environ=ENV))
    app.state.super_client = FakeSuper(GOOD_SUMMARY)
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        with session_scope(app.state.engine) as s:
            s.add(Task(id="task-1", owner_id="mary", status="calling", intake_json="{}", windows_json=json.dumps(WINDOWS)))
            s.add(Call(id="call-a", task_id="task-1", clinic_name="Bright Smile Dental", clinic_phone="+15555550111", status="live", external_ref="conv-a"))
            s.add(Call(id="call-b", task_id="task-1", clinic_name="Smile Co.", clinic_phone="+15555550112", status="live"))
        yield c


def post(client, body, *, secret=WEBHOOK_SECRET, headers=None):
    raw = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if secret is not None:
        h["ElevenLabs-Signature"] = sign(raw, secret)
    h.update(headers or {})
    return client.post("/api/webhooks/elevenlabs/post-call", content=raw, headers=h)


def events(app, kind=None):
    with session_scope(app.state.engine) as s:
        rows = s.exec(select(Event).order_by(Event.id)).all()
        return [(r.type, r.visibility, json.loads(r.payload_json)) for r in rows if kind is None or r.type == kind]


def call(app, call_id="call-a"):
    with session_scope(app.state.engine) as s:
        row = s.get(Call, call_id)
        return row.status, json.loads(row.result_json) if row.result_json else None, row.external_ref


# --- signature --------------------------------------------------------------------------------------


def test_unsigned_request_is_rejected_when_a_secret_is_set(client, app):
    assert post(client, payload(), secret=None).status_code == 401
    assert events(app) == []


def test_wrong_secret_and_stale_timestamp_are_rejected(client):
    assert post(client, payload(), secret="not-the-secret").status_code == 401
    raw = json.dumps(payload()).encode()
    stale = sign(raw, WEBHOOK_SECRET, at=int(time.time()) - 31 * 60)
    assert client.post("/api/webhooks/elevenlabs/post-call", content=raw, headers={"Content-Type": "application/json", "ElevenLabs-Signature": stale}).status_code == 401


def test_verify_signature_matches_the_vendor_scheme():
    raw = b'{"a":1}'
    header = sign(raw, "s3cret", at=1_700_000_000)
    assert header.startswith("t=1700000000,v0=")
    verify_signature(raw, header, "s3cret", now=1_700_000_100)
    with pytest.raises(HTTPException):
        verify_signature(raw, header, "s3cret", now=1_700_000_000 + 31 * 60)
    with pytest.raises(HTTPException):
        verify_signature(raw + b" ", header, "s3cret", now=1_700_000_100)
    with pytest.raises(HTTPException):
        verify_signature(raw, "t=1700000000", "s3cret", now=1_700_000_100)


def test_unsigned_is_accepted_only_in_development_without_a_secret():
    dev = create_app(load_settings(env_file=None, environ={k: v for k, v in ENV.items() if k != "ELEVENLABS_WEBHOOK_SECRET"}))
    with TestClient(dev) as c:
        assert c.post("/api/webhooks/elevenlabs/post-call", json={"type": "other"}).status_code == 200
    prod = create_app(load_settings(env_file=None, environ={**{k: v for k, v in ENV.items() if k != "ELEVENLABS_WEBHOOK_SECRET"},
                                                           "APP_ENV": "production", "DASHBOARD_SESSION_SECRET": "x" * 32}))
    with TestClient(prod) as c:
        assert c.post("/api/webhooks/elevenlabs/post-call", json={"type": "other"}).status_code == 503


# --- happy path from data collection -------------------------------------------------------------------


def test_data_collection_fields_become_call_result_and_done(client, app):
    r = post(client, payload())
    assert r.status_code == 200 and r.json()["accepted"] == "post_call_transcription"
    assert events(app) == [
        ("call_result", "contact", {"call_id": "call-a", "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True}),
        ("call_status", "contact", {"call_id": "call-a", "status": "done"}),
    ]
    status, stored, _ = call(app)
    assert status == "done"
    assert stored["price_usd"] == 95.0 and stored["slot_start"] == "2026-11-26T09:30:00-06:00" and stored["source"] == "data_collection"
    assert app.state.super_client.calls == []  # Super not needed


def test_slot_outside_windows_is_reported_with_slotok_false(client, app):
    post(client, payload({"price": "$120", "slot": "Fri 4:00", "insured": "Yes"}))
    (result,) = events(app, "call_result")
    assert result[2] == {"call_id": "call-a", "price": "$120", "slot": "Fri 4:00", "insured": True, "slotOk": False}


def test_matching_falls_back_to_the_dynamic_variable_call_id(client, app):
    post(client, payload(conversation_id="conv-b", call_id="call-b"))
    status, stored, external_ref = call(app, "call-b")
    assert status == "done" and stored["slotOk"] is True
    assert external_ref == "conv-b"  # learned from the webhook


def test_unknown_conversation_is_ignored_with_200(client, app):
    r = post(client, payload(conversation_id="conv-zzz", call_id="call-zzz"))
    assert r.status_code == 200
    assert events(app) == []


def test_unhandled_event_type_is_ignored(client, app):
    assert post(client, payload(kind="post_call_audio")).json() == {"ok": True, "ignored": "unhandled_type"}
    assert events(app) == []


# --- T8: duplicate webhook -------------------------------------------------------------------------------


def test_duplicate_webhook_creates_no_second_call_result(client, app):
    post(client, payload())
    post(client, payload())
    post(client, payload({"price": "$1", "slot": "Mon 8:00", "insured": "no"}))  # even a changed retry does not rewrite
    assert len(events(app, "call_result")) == 1
    assert len(events(app, "call_status")) == 1
    assert call(app)[1]["price_usd"] == 95.0


# --- Super fallback ------------------------------------------------------------------------------------


def test_missing_fields_are_filled_by_super_from_the_transcript(client, app):
    post(client, payload({"price": "", "insured": None}))  # slot missing too
    (result,) = events(app, "call_result")
    assert result[2] == {"call_id": "call-a", "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True}
    assert call(app)[1]["source"] == "super"
    (req,) = app.state.super_client.calls
    sent = json.loads(req["user"])
    assert sent["timezone"] == "America/Chicago"
    assert any("Thursday at 9:30" in line for line in sent["transcript"])


def test_data_collection_wins_and_super_fills_only_the_gap(client, app):
    app.state.super_client = FakeSuper(json.dumps({"price_usd": 999, "insured": False, "slot_start": "2026-11-26T09:30:00-06:00",
                                                   "slot_end": "2026-11-26T10:30:00-06:00", "slot_label": "Thu 9:30"}))
    post(client, payload({"price": "$95", "insured": "yes"}))  # only the slot is missing
    (result,) = events(app, "call_result")
    assert result[2]["price"] == "$95" and result[2]["insured"] is True and result[2]["slot"] == "Thu 9:30"
    assert call(app)[1]["source"] == "mixed"


def test_super_bad_reply_is_retried_once_then_result_stays_incomplete(client, app):
    app.state.super_client = FakeSuper("prose", json.dumps({"price_usd": "cheap"}))
    post(client, payload({}))
    assert events(app, "call_result") == []
    assert events(app, "call_status") == [("call_status", "contact", {"call_id": "call-a", "status": "done"})]
    assert call(app)[1]["source"] == "incomplete"
    assert len(app.state.super_client.calls) == 2


def test_without_super_the_result_is_incomplete_not_invented():
    app = create_app(load_settings(env_file=None, environ=ENV))  # no NEMOTRON_SUPER_ID, no fake
    with TestClient(app) as c:
        with session_scope(app.state.engine) as s:
            s.add(Task(id="task-1", owner_id="mary", status="calling", windows_json=json.dumps(WINDOWS)))
            s.add(Call(id="call-a", task_id="task-1", clinic_name="Oak Dental", clinic_phone="+15555550113", external_ref="conv-a"))
        assert post(c, payload({})).status_code == 200
        assert events(app, "call_result") == []
        assert call(app)[0] == "done" and call(app)[1]["source"] == "incomplete"


def test_summarize_call_validates_types_and_raises_after_one_retry():
    bad_pairs = [
        json.dumps({"price_usd": -5, "insured": None, "slot_start": None, "slot_end": None, "slot_label": None}),
        json.dumps({"price_usd": 95, "insured": "yes", "slot_start": None, "slot_end": None, "slot_label": None}),
        json.dumps({"price_usd": 95, "insured": True, "slot_start": "2026-11-26T09:30:00", "slot_end": "2026-11-26T10:30:00", "slot_label": "x"}),
        json.dumps({"price_usd": 95, "insured": True, "slot_start": "2026-11-26T09:30:00-06:00", "slot_end": None, "slot_label": "x"}),
    ]
    for bad in bad_pairs:
        fake = FakeSuper(bad, GOOD_SUMMARY)
        summary = summarize_call([{"speaker": "clinic", "text": "x"}], client=fake, call_date=CALL_DATE, timezone="America/Chicago")
        assert summary.price_usd == 95.0 and len(fake.calls) == 2
    with pytest.raises(SummaryError):
        summarize_call([], client=FakeSuper("no", "still no"), call_date=CALL_DATE, timezone="America/Chicago")


# --- call failure ----------------------------------------------------------------------------------------


def test_call_initiation_failure_marks_the_call_done_with_call_failed(client, app):
    body = {"type": "call_initiation_failure", "event_timestamp": 1, "data": {"conversation_id": "conv-a", "failure_reason": "busy", "metadata": {"type": "twilio"}}}
    post(client, body)
    post(client, body)
    assert events(app) == [("call_status", "contact", {"call_id": "call-a", "status": "done", "error": "CALL_FAILED", "reason": "busy"})]
    assert call(app)[1] == {"error": "CALL_FAILED", "reason": "busy"}


# --- parsers -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [("$95", 95.0), ("95 dollars", 95.0), ("$1,200.50", 1200.5), ("ninety-five", None), ("", None), (None, None)])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [("yes", True), ("Yes, they take Delta", True), ("no", False), ("Not accepted", False), ("unclear", None), (None, None)])
def test_parse_insured(text, expected):
    assert parse_insured(text) == expected


@pytest.mark.parametrize(
    "text,start",
    [
        ("Thu 9:30", "2026-11-26T09:30:00-06:00"),
        ("Thursday at 9:30 AM", "2026-11-26T09:30:00-06:00"),
        ("Fri 4:00", "2026-11-27T16:00:00-06:00"),
        ("Friday 4 pm", "2026-11-27T16:00:00-06:00"),
        ("Mon 10:00", "2026-11-23T10:00:00-06:00"),
        ("next Monday at 10", "2026-11-30T10:00:00-06:00"),
        ("Sat 12:00", "2026-11-28T12:00:00-06:00"),
        ("Tue 8 am", "2026-11-24T08:00:00-06:00"),
    ],
)
def test_parse_slot_resolves_weekday_and_clinic_hours(text, start):
    slot = parse_slot(text, call_date=CALL_DATE, tz=CHI)
    assert slot is not None
    assert slot[0].isoformat() == start
    assert (slot[1] - slot[0]).total_seconds() == 3600


@pytest.mark.parametrize("text", ["sometime next week", "9:30", "Thursday", "", None])
def test_parse_slot_refuses_what_it_cannot_resolve(text):
    assert parse_slot(text, call_date=CALL_DATE, tz=CHI) is None


def test_slot_ok_is_whole_slot_inside_one_window():
    windows = [Window(datetime(2026, 11, 26, 8, tzinfo=CHI), datetime(2026, 11, 26, 12, tzinfo=CHI))]
    assert slot_ok(datetime(2026, 11, 26, 11, tzinfo=CHI), datetime(2026, 11, 26, 12, tzinfo=CHI), windows)
    assert not slot_ok(datetime(2026, 11, 26, 11, 30, tzinfo=CHI), datetime(2026, 11, 26, 12, 30, tzinfo=CHI), windows)
    assert not slot_ok(None, None, windows)
    assert call_results.SLOT_MINUTES == 60
