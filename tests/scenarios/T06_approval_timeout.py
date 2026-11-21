"""T6 — Owner does not approve within the timeout: the task stays `awaiting_approval`; reminder SMS once; no booking."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from app import orchestrator
from harness import DEMO_NOW, OWNER_PHONE, Lab


def test_t6_nothing_is_booked_while_the_owner_has_not_answered(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    pick = lab.of_type(task_id, "approval_required")[0]
    assert pick["pick"] == {"clinic": "Bright Smile Dental", "slot": "Thu 9:30", "price": "$95"}
    assert pick["expires_at"] == (DEMO_NOW + orchestrator.APPROVAL_WINDOW).isoformat()

    lab.settle(0.5)
    assert lab.task(task_id)["status"] == "awaiting_approval"
    assert len(lab.sms_to(OWNER_PHONE)) == 1 and "Reply YES" in lab.sms_to(OWNER_PHONE)[0], "one text: the pick"
    assert lab.voice.confirmed == [] and lab.calendar_writes == []
    assert not {"approved", "booked", "booking"} & set(lab.types(task_id))
    assert lab.task(task_id)["booking"] is None

    # the owner can still answer after waiting
    assert lab.approve(task_id).json() == {"status": "approved", "applied": True}
    lab.wait_for(task_id, "awaiting_contact")


@pytest.mark.xfail(reason="#22 (PR #80): one reminder SMS on approval timeout is not merged yet", strict=False)
def test_t6_timeout_sends_one_reminder_and_keeps_waiting(lab: Lab, monkeypatch):
    monkeypatch.setattr(orchestrator, "APPROVAL_WINDOW", timedelta(milliseconds=100))
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")

    deadline = time.time() + 3
    while time.time() < deadline and len(lab.sms_to(OWNER_PHONE)) < 2:
        time.sleep(0.02)
    lab.settle(0.5)
    assert len(lab.sms_to(OWNER_PHONE)) == 2, "the pick, then exactly one reminder"
    assert lab.task(task_id)["status"] == "awaiting_approval"
    assert any(e.get("reason") == "APPROVAL_TIMEOUT" for e in lab.of_type(task_id, "task_updated")), "the timeout is an event, not a silent wait"
    assert lab.voice.confirmed == [] and lab.calendar_writes == [] and "booked" not in lab.types(task_id)

    assert lab.approve(task_id).json()["applied"] is True
    lab.wait_for(task_id, "awaiting_contact")
    assert lab.voice.confirmed and len(lab.calendar_writes) == 1
