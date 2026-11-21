"""T10 — Contact declines: the task stays `awaiting_contact`; the owner is told; no false ride confirmation."""

from __future__ import annotations

import pytest
from harness import CONTACT, CONTACT_PHONE, Lab


def booked_and_waiting(lab: Lab) -> str:
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    lab.wait_for(task_id, "awaiting_contact")
    return task_id


def test_t10_dashboard_decline_keeps_the_task_open_and_tells_the_owner(lab: Lab):
    task_id = booked_and_waiting(lab)
    r = lab.offer(task_id, can_drive=False)
    assert r.status_code == 200 and r.json() == {"status": "awaiting_contact", "ride": "declined"}
    lab.settle(0.3)

    assert lab.task(task_id)["status"] == "awaiting_contact"
    reply = lab.of_type(task_id, "contact_reply")[-1]
    assert reply["contact"] == "Sarah" and reply["offer"]["can_drive"] is False, "the owner's view carries the decline"
    assert reply["visibility"] == "contact", "both roles see it"
    assert "ride_confirmed" not in lab.types(task_id) and "notified" not in lab.types(task_id)
    assert lab.types(task_id)[-1] == "contact_reply"
    assert lab.of_type(task_id, "contact_reply", CONTACT) == lab.of_type(task_id, "contact_reply")

    # a second decline is a second honest reply; a later offer still closes the task, once
    lab.offer(task_id, can_drive=False)
    assert lab.types(task_id).count("contact_reply") == 2 and lab.task(task_id)["status"] == "awaiting_contact"
    assert lab.offer(task_id, can_drive=True).json()["status"] == "ride_confirmed"
    lab.wait_for(task_id, "completed")
    assert lab.types(task_id).count("ride_confirmed") == 1
    lab.validate_trail(task_id)


@pytest.mark.xfail(reason="#23 (PR #81): the contact's SMS reply through POST /api/webhooks/twilio/sms is not merged yet", strict=False)
def test_t10_sms_no_keeps_waiting_and_a_later_yes_confirms(lab: Lab):
    task_id = booked_and_waiting(lab)
    assert lab.twilio_sms(CONTACT_PHONE, "NO", "SM-t10-no").status_code == 200
    lab.settle(0.3)
    assert lab.task(task_id)["status"] == "awaiting_contact"
    reply = lab.of_type(task_id, "contact_reply")[-1]
    assert reply["offer"]["can_drive"] is False and "ride_confirmed" not in lab.types(task_id)
    # the owner is told in their own view; the contact's view carries the reply, not the owner's note
    declined = [e for e in lab.of_type(task_id, "task_updated") if e.get("reason") == "CONTACT_DECLINED"]
    assert len(declined) == 1 and declined[0]["visibility"] == "owner" and declined[0]["status"] == "awaiting_contact"
    assert not [e for e in lab.of_type(task_id, "task_updated", CONTACT) if e.get("reason") == "CONTACT_DECLINED"]

    assert lab.twilio_sms(CONTACT_PHONE, "YES", "SM-t10-yes").status_code == 200
    lab.wait_for(task_id, "completed")
    assert lab.types(task_id).count("ride_confirmed") == 1
