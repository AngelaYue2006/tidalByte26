"""Issue #22: approval by dashboard POST or by SMS YES from the owner's allowlisted number; NO cancels; one reminder after
APPROVAL_TIMEOUT_MIN then the task keeps waiting (T6); a duplicate SMS is a no-op (T8); an unknown number is ignored (T9)."""

from __future__ import annotations

import time

import pytest
from app import approvals
from app.adapters import Deps
from app.config import load_settings
from app.main import create_app
from app.routers.webhooks import handle_inbound
from fastapi.testclient import TestClient

from tests.stand_ins import FakeNano, FakeSuper
from tests.test_pipeline_mock import (
    DEMO_NOW,
    FAKE_PHONES,
    CountingVoice,
    events,
    start,
    wait_for,
)

OWNER_PHONE = "+15555550100"
CONTACT_PHONE = "+15555550101"
STRANGER_PHONE = "+15555550199"  # not on the allowlist


def make_client(monkeypatch, tmp_path, *, timeout_min: float = 10.0):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)
    for var in ("VOICE_MODE", "PLACES_MODE", "CALENDAR_MODE", "SMS_MODE", "TRANSPORT_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    settings = load_settings(env_file=None, environ={
        "DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db", "DEMO_PHONE_ALLOWLIST": FAKE_PHONES, "APPROVAL_TIMEOUT_MIN": str(timeout_min),
    })
    deps = Deps(voice=CountingVoice(), intake_model=lambda: FakeNano(), rank_client=FakeSuper, now=lambda: DEMO_NOW)
    client = TestClient(create_app(settings, deps=deps))
    client.__enter__()
    assert client.get("/api/session").json() == {"ok": True}
    return client


@pytest.fixture
def client(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    yield c
    c.__exit__(None, None, None)


def sms(client, body, *, sender=OWNER_PHONE, sid="SM0001", task_id=None):
    """Post the Twilio form through the route (always 200 with empty TwiML), then read the handler's outcome by re-delivering
    the same MessageSid, which is idempotent and reports the same result."""
    form = {"From": sender, "To": "+15555550199", "Body": body, "MessageSid": sid}
    if task_id:
        form["task_id"] = task_id
    r = client.post("/api/webhooks/twilio/sms", data=form)
    assert_empty_twiml(r)
    return handle_inbound(client.app, form)


def assert_empty_twiml(r):
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.headers["content-type"].startswith("text/xml")
    assert r.text == '<?xml version="1.0" encoding="UTF-8"?><Response/>'


def types(client, task_id):
    return [e["type"] for e in events(client, task_id)]


# --- SMS YES / NO -------------------------------------------------------------------------------------


def test_owner_sms_yes_approves_and_the_pipeline_continues(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, "YES") == {"ok": True, "task_id": task_id, "status": "approved", "applied": True}
    wait_for(client, task_id, "awaiting_contact")
    approved = [e for e in events(client, task_id) if e["type"] == "approved"]
    assert approved == [{**approved[0], "by": "mary", "via": "sms"}]
    assert types(client, task_id).count("approved") == 1
    assert "booked" in types(client, task_id)  # booking happened only after the approved event


@pytest.mark.parametrize("word", ["y", "Yes.", " yes ", "OK", "approve"])
def test_yes_synonyms_approve(client, word):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, word)["applied"] is True
    wait_for(client, task_id, "awaiting_contact")


@pytest.mark.parametrize("word", ["NO", "n", "no.", "reject", "cancel"])
def test_owner_sms_no_cancels(client, word):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, word) == {"ok": True, "task_id": task_id, "status": "cancelled", "applied": True}
    wait_for(client, task_id, "cancelled")
    assert "approved" not in types(client, task_id) and "booked" not in types(client, task_id)
    last = [e for e in events(client, task_id) if e["type"] == "task_updated"][-1]
    assert last["status"] == "cancelled" and last["reason"] == "REJECTED_BY_OWNER"


def test_duplicate_sms_is_a_no_op(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    first = sms(client, "YES", sid="SM-dup")
    again = sms(client, "YES", sid="SM-dup")  # Twilio retried the webhook
    assert first == again
    wait_for(client, task_id, "awaiting_contact")
    assert types(client, task_id).count("approved") == 1
    later = sms(client, "YES", sid="SM-new")  # a second, different YES after approval
    assert later["applied"] is False and later["status"] in ("booking", "transport", "awaiting_contact", "completed")
    assert types(client, task_id).count("approved") == 1


def test_contact_number_cannot_approve(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, "YES", sender=CONTACT_PHONE) == {"ok": True, "ignored": "not_owner"}
    time.sleep(0.2)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
    assert "approved" not in types(client, task_id)


def test_unknown_number_is_ignored_and_leaks_nothing(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    form = {"From": "+15555550177", "To": "+15555550199", "Body": "YES", "MessageSid": "SM-x"}
    r = client.post("/api/webhooks/twilio/sms", data=form)
    assert_empty_twiml(r)  # the same empty TwiML as for anyone: nothing about the task in the reply
    assert handle_inbound(client.app, form) == {"ok": False, "ignored": "unverified_sender"}
    time.sleep(0.2)
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"


def test_unrecognised_text_and_nothing_waiting_are_ignored(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, "What time is it?") == {"ok": True, "ignored": "not_an_answer"}
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
    sms(client, "YES", sid="SM-go")
    wait_for(client, task_id, "awaiting_contact")
    assert sms(client, "NO", sid="SM-late")["ignored"] == "not_awaiting_approval"


def test_correlated_task_id_must_belong_to_the_owner(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    assert sms(client, "YES", task_id="not-a-task") == {"ok": True, "ignored": "nothing_waiting"}
    assert sms(client, "YES", task_id=task_id, sid="SM-corr")["applied"] is True


def test_decision_words():
    assert approvals.decision_from_text("  YES ") == "approve"
    assert approvals.decision_from_text("No") == "reject"
    assert approvals.decision_from_text("yes please book it") is None
    assert approvals.decision_from_text("") is None


# --- dashboard route still behaves as before -----------------------------------------------------------------


def test_dashboard_approve_emits_via_dashboard_and_sms_then_is_idempotent(client):
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    r = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={"actor_id": "mary", "decision": "approve", "idempotency_key": "k"})
    assert r.json() == {"status": "approved", "applied": True}
    approved = [e for e in events(client, task_id) if e["type"] == "approved"]
    assert approved[0]["by"] == "mary" and approved[0]["via"] == "dashboard"
    wait_for(client, task_id, "awaiting_contact")
    assert sms(client, "YES")["applied"] is False
    assert types(client, task_id).count("approved") == 1


# --- T6: one reminder, then keep waiting --------------------------------------------------------------------------


def test_t6_no_answer_sends_one_reminder_and_keeps_waiting(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, timeout_min=0.005)  # 0.3 s
    try:
        task_id = start(client)
        wait_for(client, task_id, "awaiting_approval")
        required = next(e for e in events(client, task_id) if e["type"] == "approval_required")
        assert required["expires_at"] == "2026-11-23T09:00:00.300000-06:00"
        time.sleep(1.2)  # four timeouts' worth
        reminders = [e for e in events(client, task_id) if e["type"] == "task_updated" and e.get("reason") == "APPROVAL_TIMEOUT"]
        assert len(reminders) == 1
        assert reminders[0]["status"] == "awaiting_approval" and reminders[0]["visibility"] == "owner"
        assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "awaiting_approval"
        assert "booked" not in types(client, task_id) and "approved" not in types(client, task_id)
        sarah = events(client, task_id, viewer="sarah")
        assert not any(e.get("reason") == "APPROVAL_TIMEOUT" for e in sarah)  # the reminder is the owner's business
        assert sms(client, "YES")["applied"] is True  # the late answer still counts
        wait_for(client, task_id, "awaiting_contact")
        assert types(client, task_id).count("approved") == 1
    finally:
        client.__exit__(None, None, None)


def test_a_timely_answer_sends_no_reminder(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, timeout_min=0.02)  # 1.2 s
    try:
        task_id = start(client)
        wait_for(client, task_id, "awaiting_approval")
        sms(client, "YES")
        wait_for(client, task_id, "awaiting_contact")
        time.sleep(1.5)
        assert not any(e.get("reason") == "APPROVAL_TIMEOUT" for e in events(client, task_id))
    finally:
        client.__exit__(None, None, None)


def test_inbound_sms_log_names_the_outcome_but_never_a_number_or_the_text(client, caplog):
    """From the #7 kickoff stub: what Twilio sent is evidence for the log, the phone numbers and the body are not."""
    import logging

    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    with caplog.at_level(logging.INFO, logger="lifeline.webhooks"):
        sms(client, "YES", sid="SM-log-1")
        sms(client, "hello? is this Mary's clinic", sender=STRANGER_PHONE, sid="SM-log-2")
    assert "'applied': True" in caplog.text and "unverified_sender" in caplog.text
    for secret in (OWNER_PHONE, STRANGER_PHONE, "hello?", "Mary", task_id, "SM-log"):
        assert secret not in caplog.text
