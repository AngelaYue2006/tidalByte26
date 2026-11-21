"""T7 — Clinic says "we'll call back to confirm": appointment `tentative`; no calendar event; the dashboard says so."""

from __future__ import annotations

from harness import BRIGHT, CONTACT, Lab, ScenarioVoice


def test_t7_tentative_confirmation_creates_no_calendar_event_and_says_so(lab_factory):
    lab: Lab = lab_factory(voice=ScenarioVoice(booking_replies={BRIGHT: "tentative"}))
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    task = lab.wait_for(task_id, "awaiting_contact")

    assert task["booking"]["status"] == "tentative" and task["booking"]["calendar_event_id"] is None
    assert task["booking"]["confirmation_ref"] is None
    assert lab.calendar_writes == [], "no calendar write without a confirmed receipt"
    booked = lab.of_type(task_id, "booked")[0]
    assert booked["tentative"] is True and booked["calendar"] == ""
    assert "call back to confirm" in booked["sms_user"] and "Nothing is on your calendar yet" in booked["sms_user"]
    assert lab.of_type(task_id, "booked", CONTACT)[0]["tentative"] is True
    _, snap = lab.snapshot()
    assert snap["task"]["booking"]["status"] == "tentative" and snap["task"]["booking"]["calendar_event_id"] is None
    lab.validate_trail(task_id)


def test_t7_rejected_confirmation_fails_the_task_instead_of_pretending(lab_factory):
    """Status comes from the receipt: a clinic that does not confirm leaves nothing booked and nothing on the calendar."""
    lab: Lab = lab_factory(voice=ScenarioVoice(booking_replies={BRIGHT: "rejected"}))
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    task = lab.wait_for(task_id, "failed")
    assert task["failure_reason"] == "BOOKING_REJECTED" and task["booking"] is None
    assert lab.calendar_writes == [] and "booked" not in lab.types(task_id)
    assert "did not confirm" in lab.of_type(task_id, "task_updated")[-1]["message"]
