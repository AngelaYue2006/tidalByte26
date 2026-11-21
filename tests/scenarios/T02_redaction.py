"""T2 — Raw request with symptoms and a member ID: the chips contain neither, and the outbound request log shows no raw text.

The raw utterance reaches Nano (on the device) and the owner's own view, and nothing else: not the chips, not the contact
view, not the clinic call specs, not the ranker prompt, not an SMS, not a log line at INFO, not the metrics file.
"""

from __future__ import annotations

import logging

from harness import CONTACT, DEMO_CHIPS, FakeNano, Lab

RAW = (
    "This is Mary Johnson, member ID DEMO-0000-0000-0001. I need a dental cleaning this week, under $150, and I have Delta Dental. "
    "My tooth has been aching for days and my knee makes walking hard, so I'll need a ride."
)
PROPOSAL = {
    "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental", "time_phrase": "this week",
    "needs_ride": True, "search_area": "near home", "dropped_fields": ["symptoms", "member_id", "patient_name", "mobility_details"],
}
# What Nano dropped: the identifier, the symptom, the mobility detail, the name. None of it may appear anywhere but on the device.
SENSITIVE = (RAW, "DEMO-0000-0000-0001", "aching", "tooth has been", "knee", "Johnson", "1948-03-14")
# The owner's first name is the contact's business (the ride request names Mary); the cloud never needs it.
CLOUD_SENSITIVE = (*SENSITIVE, "Mary")


def leaked(text: str, tokens=SENSITIVE) -> list[str]:
    """The sensitive tokens present in `text`; an empty list is the only acceptable answer."""
    return [token for token in tokens if token in text]


def test_t2_chips_and_every_outbound_payload_are_free_of_the_dropped_fields(lab_factory, caplog):
    caplog.set_level(logging.INFO)
    lab: Lab = lab_factory(nano=FakeNano(PROPOSAL))
    task_id = lab.start(RAW)
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    lab.wait_for(task_id, "awaiting_contact")
    lab.offer(task_id, can_drive=True)
    task = lab.wait_for(task_id, "completed")

    # the device saw the raw text once; the owner's own view keeps it
    assert lab.nano.utterances == [RAW] and task["request_text"] == RAW

    # chips: the redacted request only
    assert task["chips"] == DEMO_CHIPS and leaked(" ".join(task["chips"])) == []
    intake = task["intake"]
    assert set(intake["dropped_fields"]) >= {"symptoms", "member_id", "mobility_details"}
    assert all(name.isidentifier() for name in intake["dropped_fields"]), "dropped_fields carries names, never values"
    assert leaked(str(intake), CLOUD_SENSITIVE) == []

    # the contact view: nothing Nano dropped, and no raw text
    contact_events = lab.events(task_id, CONTACT)
    assert contact_events and all("text" not in e for e in contact_events if e["type"] == "request")
    assert leaked(str(contact_events)) == [], "the contact sees the owner's first name in the ride request, and nothing Nano dropped"
    assert "request_text" not in lab.task(task_id, CONTACT)

    # the outbound log: everything that left the pipeline through an adapter or a cloud model
    cloud = [o for o in lab.outbound if o.to_cloud]
    assert {o.target for o in cloud} == {"find_clinics", "drive", "rank", "voice.call_clinics"}
    for call in cloud:
        assert leaked(call.payload, CLOUD_SENSITIVE) == [], call.target
    for call in lab.outbound:
        assert leaked(call.payload) == [], call.target
    for _to, text, _key in lab.sms:
        assert leaked(text) == [], text
    assert "DEMO" not in lab.of_type(task_id, "contact_request")[0]["message"]

    # the log at INFO and the metrics file: numbers and field names only
    assert leaked(caplog.text) == []
    rows = lab.metrics_rows()
    intake_rows = [r for r in rows if r["kind"] == "intake"]
    assert intake_rows and set(intake_rows[0]["dropped"]) >= {"symptoms", "member_id"}
    assert leaked(lab.metrics_path.read_text()) == []


def test_t2_a_leaking_model_proposal_is_refused_before_anything_leaves(lab_factory):
    """Nano proposes a care type that carries a symptom: the device fails closed and no cloud call is made."""
    lab: Lab = lab_factory(nano=FakeNano({**PROPOSAL, "care_type": "knee pain cleaning"}))
    task_id = lab.start(RAW)
    task = lab.wait_for(task_id, "failed")
    assert task["failure_reason"] == "INTAKE_INCOMPLETE" and task["intake"] is None and task["chips"] == []
    assert [o for o in lab.outbound if o.to_cloud] == [] and lab.sms == []
    assert "request" not in lab.types(task_id) and "call_start" not in lab.types(task_id)
    failure = lab.of_type(task_id, "task_updated")[-1]
    assert failure["status"] == "failed" and leaked(failure["message"], CLOUD_SENSITIVE) == []
    # contacts are seeded once intake succeeds, so the contact view answers 404 here: still nothing to leak
    contact_view = lab.client.get(f"/api/tasks/{task_id}/events?viewer_id={CONTACT}")
    assert contact_view.status_code == 404 or leaked(contact_view.text, CLOUD_SENSITIVE) == []
