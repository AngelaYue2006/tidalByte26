"""T9 — Reply from a number not on the allowlist: rejected, logged, no task data leaked."""

from __future__ import annotations

import logging
import re

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


def test_t9_sms_from_an_unknown_number_is_rejected_and_logged(lab: Lab, caplog):
    caplog.set_level(logging.INFO)
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    before = lab.events(task_id)
    records_before = len(caplog.records)

    # Twilio retries anything that is not 2xx, and a rejected sender must learn nothing: 200, empty TwiML, no facts.
    r = lab.twilio_sms(UNKNOWN_PHONE, "YES", "SM-t9-unknown")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/xml") and "<Response" in r.text
    body = re.sub(r"\s", "", r.text)
    assert body in ("<?xmlversion=\"1.0\"encoding=\"UTF-8\"?><Response/>", "<Response/>", "<Response></Response>", "<?xmlversion=\"1.0\"encoding=\"UTF-8\"?><Response></Response>"), r.text
    assert task_id not in r.text and not any(clinic in r.text for clinic in (BRIGHT, SMILE, OAK)) and "Thu 9:30" not in r.text

    # logged, without the sender's number or any task text
    new_records = caplog.records[records_before:]
    assert any(rec.levelno >= logging.WARNING for rec in new_records), "the rejection is logged"
    logged = "\n".join(rec.getMessage() for rec in new_records)
    assert UNKNOWN_PHONE not in logged and UNKNOWN_PHONE[-7:] not in logged
    assert not any(clinic in logged for clinic in (BRIGHT, SMILE, OAK)) and "Thu 9:30" not in logged

    lab.settle(0.3)
    assert lab.events(task_id) == before, "no event, no state change"
    assert lab.task(task_id)["status"] == "awaiting_approval" and lab.voice.confirmed == [] and lab.calendar_writes == []
