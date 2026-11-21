"""T8 — Repeated webhooks and retries: no duplicate SMS, booking or calendar event.

The three replays that exist today (the request key, the approval key, the contact-offer key) and the ElevenLabs
post-call webhook are tested against the running backend; the Twilio SMS webhook replay waits on #22.
"""

from __future__ import annotations

import pytest
from harness import BRIGHT, CONTACT_PHONE, DEMO_NOW, OWNER_PHONE, Lab


def test_t8_repeated_request_approval_and_offer_apply_once(lab: Lab):
    first = lab.client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "text": "I need a dental cleaning this week, under $150. I have Delta Dental. I'll need a ride.", "idempotency_key": "t8-request"})
    again = lab.client.post("/api/requests?viewer_id=mary", json={"owner_id": "mary", "actor_id": "mary", "text": "I need a dental cleaning this week, under $150. I have Delta Dental. I'll need a ride.", "idempotency_key": "t8-request"})
    assert first.status_code == 201 and again.status_code == 200 and first.json() == again.json()
    task_id = first.json()["task_id"]
    lab.wait_for(task_id, "awaiting_approval")
    assert [t["id"] for t in lab.history()] == [task_id], "one task, one pipeline"
    sms_before = list(lab.sms)

    assert lab.approve(task_id, key="t8-approve").json() == lab.approve(task_id, key="t8-approve").json() == {"status": "approved", "applied": True}
    lab.wait_for(task_id, "awaiting_contact")
    assert lab.approve(task_id, key="t8-approve-later").json()["applied"] is False
    assert lab.types(task_id).count("approved") == 1 and lab.types(task_id).count("booked") == 1
    assert lab.voice.confirmed == [lab.call_ids(task_id)[BRIGHT]] and len(lab.calendar_writes) == 1
    assert len(lab.sms) == len(sms_before) + 2, "booked text to the owner, ride request to the contact, nothing twice"

    yes = lab.offer(task_id, can_drive=True, key="t8-ride")
    assert yes.json() == lab.offer(task_id, can_drive=True, key="t8-ride").json() and yes.json()["status"] == "ride_confirmed"
    assert lab.offer(task_id, can_drive=True, key="t8-ride-later").status_code == 409
    lab.wait_for(task_id, "completed")
    assert lab.types(task_id).count("ride_confirmed") == 1 and lab.types(task_id).count("notified") == 1
    assert len(lab.sms_to(OWNER_PHONE)) == 3 and len(lab.sms_to(CONTACT_PHONE)) == 2


def test_t8_repeated_post_call_webhook_adds_no_result_event(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    bright = lab.call_ids(task_id)[BRIGHT]
    before = lab.events(task_id)
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": int(DEMO_NOW.timestamp()),
        "data": {
            "agent_id": "agent-x", "conversation_id": "conv-t8", "status": "done",
            "transcript": [{"role": "agent", "message": "Hi, I'm an AI assistant calling for a patient.", "time_in_call_secs": 1}],
            "analysis": {"data_collection_results": {"price": "$95", "slot": "Thu 9:30", "insured": "yes"}, "call_successful": "success"},
            "conversation_initiation_client_data": {"dynamic_variables": {"call_id": bright}},
        },
    }
    for _ in range(2):
        r = lab.post_call_webhook(payload)
        assert r.status_code == 200 and r.json()["duplicate"] is True, r.text
    assert lab.events(task_id) == before
    assert lab.types(task_id).count("call_result") == 3
    assert lab.task(task_id)["status"] == "awaiting_approval" and lab.voice.confirmed == []


@pytest.mark.xfail(reason="#22 (PR #80): POST /api/webhooks/twilio/sms and the SMS YES approval are not merged yet", strict=False)
def test_t8_repeated_twilio_yes_books_once(lab: Lab):
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    sms_before = len(lab.sms)
    first = lab.twilio_sms(OWNER_PHONE, "YES", "SM-t8-yes")
    retry = lab.twilio_sms(OWNER_PHONE, "YES", "SM-t8-yes")  # Twilio retries the same MessageSid
    assert first.status_code == 200 and retry.status_code == 200, "Twilio must always get a 2xx"
    assert first.headers["content-type"].startswith("text/xml") and "<Response" in first.text
    lab.wait_for(task_id, "awaiting_contact")
    approved = lab.of_type(task_id, "approved")
    assert len(approved) == 1 and approved[0]["via"] == "sms"
    assert lab.voice.confirmed == [lab.call_ids(task_id)[BRIGHT]] and len(lab.calendar_writes) == 1
    assert lab.types(task_id).count("booked") == 1
    assert len(lab.sms) == sms_before + 2, "booked text and the ride request, once each"
