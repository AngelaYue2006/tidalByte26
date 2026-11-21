"""T9 — Reply from a number not on the allowlist: rejected, logged, no task data leaked."""

from __future__ import annotations

import logging

import pytest
from harness import BRIGHT, OAK, SMILE, UNKNOWN_PHONE, Lab

STRANGER = "stranger"  # a viewer id that is neither the owner nor a row in contacts


def test_t9_a_viewer_outside_the_owner_and_contact_gets_no_task_data(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    assert lab.client.get(f"/api/tasks/{task_id}?viewer_id={STRANGER}").status_code == 404
    assert lab.client.get(f"/api/tasks/{task_id}/events?viewer_id={STRANGER}").status_code == 404
    assert lab.history(STRANGER) == [] and lab.history(STRANGER, owner_id="mary") == []
    _, snap = lab.snapshot(STRANGER)
    assert snap == {"type": "snapshot", "task": None, "calls": [], "events": []}
    assert lab.approve(task_id, actor=STRANGER).status_code == 403
    assert lab.task(task_id)["status"] == "awaiting_approval"


@pytest.mark.xfail(reason="#22 (PR #80): POST /api/webhooks/twilio/sms is not merged yet", strict=False)
def test_t9_sms_from_an_unknown_number_is_rejected_and_logged(lab: Lab, caplog):
    caplog.set_level(logging.INFO)
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    before = lab.events(task_id)

    r = lab.twilio_sms(UNKNOWN_PHONE, "YES", "SM-t9-unknown")
    assert r.status_code in (401, 403), r.text
    body = r.text
    assert task_id not in body and not any(clinic in body for clinic in (BRIGHT, SMILE, OAK)) and "Thu 9:30" not in body
    assert "UNVERIFIED_SENDER" in caplog.text, "the rejection is logged under its error code"
    assert task_id not in caplog.text or "UNVERIFIED_SENDER" in caplog.text

    lab.settle(0.3)
    assert lab.events(task_id) == before, "no event, no state change"
    assert lab.task(task_id)["status"] == "awaiting_approval" and lab.voice.confirmed == [] and lab.calendar_writes == []
