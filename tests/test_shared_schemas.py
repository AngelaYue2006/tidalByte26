"""Issue #2: every shared schema loads, is a valid Draft 2020-12 schema, and accepts one example per shape.

The negative cases guard the two scoping rules: dropped_fields carries names, never values, and the
contact task projection never carries request_text.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SHARED = Path(__file__).resolve().parents[1] / "shared"
SCHEMA_FILES = ["events.schema.json", "intake_request.schema.json", "decision.schema.json", "task.schema.json"]

# The event list in docs/ARCHITECTURE.md, Live events.
EVENT_TYPES = [
    "request", "call_start", "call_status", "transcript", "call_result", "decision", "booked", "notified",
    "approval_required", "approved", "transport_check", "contact_request", "contact_reply", "ride_confirmed",
    "task_updated", "snapshot", "heartbeat",
]

INTAKE = {
    "care_type": "dental cleaning",
    "budget_max": 150,
    "insurance_carrier": "Delta Dental",
    "time_range": {"start": "2026-11-23T00:00:00-06:00", "end": "2026-11-29T23:59:59-06:00"},
    "needs_ride": True,
    "search_area": "near home",
    "dropped_fields": ["symptoms", "member_id", "mobility_details"],
}

DECISION = {
    "winner_call_id": "a",
    "score": 0.92,
    "reasons": ["Fits your free time · Thu 9:30", "Cheapest · $95 vs $120, $140", "Takes Delta Dental"],
    "second": ["2nd closest · 1.2 mi"],
    "tradeoff": "Smile Co. is closer (0.6 mi), but its only opening is Friday at 4, when your calendar is busy.",
    "ranked": [{"call_id": "a", "score": 0.92}, {"call_id": "b", "score": 0.61}, {"call_id": "c", "score": 0.4}],
}

CALL = {
    "call_id": "a",
    "clinic": "Bright Smile Dental",
    "meta": "1.2 mi · 6 min",
    "status": "done",
    "result": {"price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True},
}

OWNER_TASK = {
    "id": "task_01",
    "owner_id": "mary",
    "status": "awaiting_approval",
    "viewer_role": "owner",
    "intake": INTAKE,
    "chips": ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"],
    "windows": [{"start": "2026-11-26T08:00:00-06:00", "end": "2026-11-26T12:00:00-06:00"}],
    "calls": [CALL],
    "decision": DECISION,
    "booking": None,
    "transport": None,
    "request_text": "I need a dental cleaning this week, under $150. I have Delta Dental.",
    "created_at": "2026-11-21T15:00:00-06:00",
    "updated_at": "2026-11-21T15:00:40-06:00",
}

CONTACT_TASK = {k: v for k, v in OWNER_TASK.items() if k != "request_text"} | {"viewer_role": "contact"}

EXAMPLE_EVENTS = {
    "request": {"type": "request", "text": "I need a dental cleaning this week, under $150.", "chips": OWNER_TASK["chips"]},
    "call_start": {"type": "call_start", "call_id": "a", "clinic": "Bright Smile Dental", "meta": "1.2 mi · 6 min"},
    "call_status": {"type": "call_status", "call_id": "a", "status": "live"},
    "transcript": {"type": "transcript", "call_id": "a", "seq": 1, "speaker": "agent",
                   "text": "Hi, I'm an AI assistant calling for a patient. Do you take Delta Dental?"},
    "call_result": {"type": "call_result", "call_id": "a", "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True},
    "decision": {"type": "decision", "winner": "a", "title": "Why Nemotron picked Bright Smile Dental",
                 "reasons": DECISION["reasons"], "second": DECISION["second"], "tradeoff": DECISION["tradeoff"]},
    "booked": {"type": "booked", "calendar": "Appointment · Thu Nov 26 · 9:30–10:30 AM",
               "sms_user": "GranniAI: Booked Bright Smile Dental, Thu Nov 26, 9:30 AM, $95 with Delta."},
    "notified": {"type": "notified", "sms_contact": "GranniAI: Appointment booked for Mary.", "sms_user": "GranniAI: All set."},
    "approval_required": {"type": "approval_required", "pick": {"clinic": "Bright Smile Dental", "slot": "Thu 9:30", "price": "$95"},
                          "expires_at": "2026-11-21T15:10:00-06:00"},
    "approved": {"type": "approved", "by": "mary", "via": "dashboard"},
    "transport_check": {"type": "transport_check", "status": "unavailable", "reason": "UNAVAILABLE_ACCESSIBLE_RIDE", "simulated": True},
    "contact_request": {"type": "contact_request", "contact": "Sarah",
                        "message": "Mary has a dental appointment Thu Nov 26 at 9:30 AM at Bright Smile Dental, 123 Main St. No accessible ride is available. Can you drive?"},
    "contact_reply": {"type": "contact_reply", "contact": "Sarah", "text": "I can drive her.",
                      "offer": {"can_drive": True, "pickup_time": "2026-11-26T09:00:00-06:00"}},
    "ride_confirmed": {"type": "ride_confirmed", "driver": "Sarah", "pickup_time": "2026-11-26T09:00:00-06:00"},
    "task_updated": {"type": "task_updated", "status": "completed"},
    "snapshot": {"type": "snapshot", "task": OWNER_TASK, "calls": [CALL],
                 "events": [{"type": "call_status", "call_id": "a", "status": "done"}]},
    "heartbeat": {"type": "heartbeat"},
}


def load(name: str) -> dict:
    return json.loads((SHARED / name).read_text())


@pytest.fixture(scope="module")
def registry() -> Registry:
    resources = [(s["$id"], Resource.from_contents(s)) for s in (load(n) for n in SCHEMA_FILES)]
    return Registry().with_resources(resources)


def validator(name: str, registry: Registry) -> Draft202012Validator:
    schema = load(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_loads_and_is_valid(name, registry):
    validator(name, registry)


def test_events_schema_covers_every_architecture_event_type():
    schema = load("events.schema.json")
    listed = [ref["$ref"].rsplit("/", 1)[1] for ref in schema["oneOf"]]
    assert listed == EVENT_TYPES
    for event_type in EVENT_TYPES:
        assert "required" in schema["$defs"][event_type] or any(
            "required" in part for part in schema["$defs"][event_type].get("allOf", [])
        ), f"{event_type} has no required fields"


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_one_example_event_validates(event_type, registry):
    v = validator("events.schema.json", registry)
    v.validate(EXAMPLE_EVENTS[event_type])


def test_event_with_unknown_type_is_rejected(registry):
    assert not validator("events.schema.json", registry).is_valid({"type": "bogus"})


def test_envelope_fields_are_accepted(registry):
    v = validator("events.schema.json", registry)
    v.validate({**EXAMPLE_EVENTS["approved"], "task_id": "task_01", "at": "2026-11-21T15:05:00-06:00", "visibility": "owner"})
    assert not v.is_valid({**EXAMPLE_EVENTS["approved"], "visibility": "everyone"})


def test_contact_request_event_never_carries_text(registry):
    v = validator("events.schema.json", registry)
    chips_only = {"type": "request", "chips": OWNER_TASK["chips"]}
    v.validate({**chips_only, "visibility": "contact"})
    v.validate({**chips_only, "text": "I need a cleaning", "visibility": "owner"})
    assert not v.is_valid({**chips_only, "text": "I need a cleaning", "visibility": "contact"})


def test_transport_check_is_always_simulated(registry):
    v = validator("events.schema.json", registry)
    assert not v.is_valid({**EXAMPLE_EVENTS["transport_check"], "simulated": False})
    assert not v.is_valid({k: val for k, val in EXAMPLE_EVENTS["transport_check"].items() if k != "simulated"})


def test_intake_request_example_validates(registry):
    validator("intake_request.schema.json", registry).validate(INTAKE)


def test_intake_dropped_fields_are_names_never_values(registry):
    v = validator("intake_request.schema.json", registry)
    for leaked in ("$150", "DD-4471-22", "1948-03-02", "knee pain", "arthritis", "metformin"):
        assert not v.is_valid({**INTAKE, "dropped_fields": [leaked]}), leaked
    assert not v.is_valid({**INTAKE, "dropped_fields": ["symptoms", "symptoms"]})


def test_intake_rejects_extra_fields(registry):
    v = validator("intake_request.schema.json", registry)
    assert not v.is_valid({**INTAKE, "member_id": "DD-4471-22"})
    assert not v.is_valid({**INTAKE, "utterance": "I need a cleaning"})


def test_decision_example_validates_and_needs_two_reasons(registry):
    v = validator("decision.schema.json", registry)
    v.validate(DECISION)
    assert not v.is_valid({**DECISION, "reasons": ["Cheapest"]})
    assert not v.is_valid({k: val for k, val in DECISION.items() if k != "tradeoff"})


def test_owner_and_contact_projections(registry):
    v = validator("task.schema.json", registry)
    v.validate(OWNER_TASK)
    v.validate(CONTACT_TASK)
    assert not v.is_valid({**CONTACT_TASK, "request_text": "I need a cleaning"})
    assert not v.is_valid({**OWNER_TASK, "status": "booked"})
