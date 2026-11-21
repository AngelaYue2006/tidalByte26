"""T1 — Standard run: Bright Smile picked, approved, booked, ride via Sarah, `completed` (docs/MVP.md, Test matrix)."""

from __future__ import annotations

from harness import (
    BRIGHT,
    CONTACT,
    CONTACT_PHONE,
    DEMO_CHIPS,
    DEMO_TEXT,
    OAK,
    OWNER_PHONE,
    SMILE,
    TASK_VALIDATOR,
    Lab,
)

STATUS_TRAIL = ["intake", "calendar", "places", "calling", "ranking", "awaiting_approval", "booking", "transport", "awaiting_contact", "completed"]

# The dashboard contract, voice events aside (call_status / transcript / call_result interleave during `calling`).
EVENT_TRAIL = [
    "task_updated", "task_updated", "request", "task_updated", "call_start", "call_start", "call_start", "task_updated",
    "task_updated", "decision", "task_updated", "approval_required", "approved", "task_updated", "booked", "task_updated",
    "transport_check", "transport_check", "task_updated", "contact_request", "contact_reply", "ride_confirmed", "notified", "task_updated",
]


def test_t1_standard_run_ends_completed_with_the_full_trail(lab: Lab):
    task_id = lab.start()

    # ranking: Bright Smile wins; nothing is booked and no calendar write happened before the one approval
    task = lab.wait_for(task_id, "awaiting_approval")
    ids = lab.call_ids(task_id)
    bright = ids[BRIGHT]
    assert set(ids) == {BRIGHT, SMILE, OAK} and all(i.startswith(task_id[:8]) for i in ids.values())
    assert task["chips"] == DEMO_CHIPS and task["request_text"] == DEMO_TEXT
    assert task["decision"]["winner_call_id"] == bright and task["booking"] is None
    assert lab.voice.confirmed == [] and lab.calendar_writes == []
    assert "booked" not in lab.types(task_id)
    assert lab.sms_to(OWNER_PHONE) and "Reply YES" in lab.sms_to(OWNER_PHONE)[0]

    # the one approval: booking confirmed, calendar event exactly once, transport finds no accessible ride
    assert lab.approve(task_id).json() == {"status": "approved", "applied": True}
    task = lab.wait_for(task_id, "awaiting_contact")
    assert task["booking"]["status"] == "confirmed" and task["booking"]["clinic"] == BRIGHT
    assert task["booking"]["calendar_event_id"] and lab.calendar_writes == [f"{task_id}:calendar"]
    assert lab.voice.confirmed == [bright]
    assert task["transport"] == {"available": False, "reason": "UNAVAILABLE_ACCESSIBLE_RIDE", "simulated": True}
    contact_request = lab.of_type(task_id, "contact_request")[0]
    assert contact_request["contact"] == "Sarah" and BRIGHT in contact_request["message"] and "123 Main St" in contact_request["message"]
    assert lab.sms_to(CONTACT_PHONE) == [contact_request["message"]]

    # Sarah offers to drive from her dashboard
    assert lab.offer(task_id, can_drive=True).json()["status"] == "ride_confirmed"
    task = lab.wait_for(task_id, "completed")

    assert [e["status"] for e in lab.of_type(task_id, "task_updated")] == STATUS_TRAIL
    assert lab.types(task_id, without_voice=True) == EVENT_TRAIL
    ride = lab.of_type(task_id, "ride_confirmed")[0]
    assert ride["driver"] == "Sarah" and ride["pickup_time"].startswith("2026-11-26T09:00")
    notified = lab.of_type(task_id, "notified")[0]
    assert "Sarah will drive you" in notified["sms_user"] and "Ride confirmed" in notified["sms_contact"]
    assert len(lab.sms_to(OWNER_PHONE)) == 3 and len(lab.sms_to(CONTACT_PHONE)) == 2  # approval, booked, final; request, final
    assert lab.voice.confirmed == [bright] and lab.calendar_writes == [f"{task_id}:calendar"]
    lab.validate_trail(task_id)


def test_t1_three_calls_show_live_transcripts_and_end_with_structured_results(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    ids = lab.call_ids(task_id)
    events = lab.events(task_id)
    for clinic, call_id in ids.items():
        statuses = [e["status"] for e in events if e["type"] == "call_status" and e["call_id"] == call_id]
        assert statuses[0] == "dialing" and statuses[-1] == "done" and "live" in statuses, clinic
        agent_lines = [e["text"] for e in events if e["type"] == "transcript" and e["call_id"] == call_id and e["speaker"] == "agent"]
        assert agent_lines and agent_lines[0].startswith("Hi, I'm an AI assistant calling for a patient"), clinic
        results = [e for e in events if e["type"] == "call_result" and e["call_id"] == call_id]
        assert len(results) == 1 and results[0]["simulated"] is True, clinic
    results = {e["call_id"]: e for e in events if e["type"] == "call_result"}
    assert {k: (results[ids[k]]["price"], results[ids[k]]["slot"], results[ids[k]]["insured"]) for k in ids} == {
        BRIGHT: ("$95", "Thu 9:30", True), SMILE: ("$120", "Fri 4:00", True), OAK: ("$140", "Mon 10:00", True),
    }
    decision = lab.of_type(task_id, "decision")[0]
    assert decision["winner"] == ids[BRIGHT] and decision["title"] == f"Why Nemotron picked {BRIGHT}"
    assert len(decision["reasons"]) >= 2 and decision["tradeoff"]
    hold = [e for e in events if e["type"] == "call_status" and e["status"] == "hold"]
    assert hold and hold[0]["call_id"] == ids[OAK], "Oak Dental's hold music reaches the card"


def test_t1_contact_view_sees_the_same_trail_without_the_raw_request(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    lab.wait_for(task_id, "awaiting_contact")
    lab.offer(task_id, can_drive=True)
    lab.wait_for(task_id, "completed")

    owner, contact = lab.events(task_id), lab.events(task_id, CONTACT)
    assert [e["type"] for e in contact] == [e["type"] for e in owner]
    assert all("text" not in e for e in contact if e["type"] == "request")
    assert DEMO_TEXT not in str(contact) and "knee" not in str(contact)
    contact_task = lab.task(task_id, CONTACT)
    assert contact_task["viewer_role"] == "contact" and "request_text" not in contact_task and contact_task["chips"] == DEMO_CHIPS
    TASK_VALIDATOR.validate(contact_task)
    # the owner's own texts (price, insurance) are not the contact's business
    assert "$95" in next(e for e in owner if e["type"] == "booked")["sms_user"]
    assert next(e for e in contact if e["type"] == "booked")["sms_user"] == ""
    assert "sms_user" not in next(e for e in contact if e["type"] == "notified")
    lab.validate_trail(task_id)
