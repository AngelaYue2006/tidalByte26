"""Issue #23: the contact message is written on the device and carries only clinic, time, address and the ride need;
the contact's SMS reply is matched to the waiting task (yes confirms once, no keeps waiting and tells the owner, T10);
a repeated MessageSid replays (T8); a sender who is not a contact on file is refused with nothing leaked (T9)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from app import contact_replies, texts
from app.nemotron import local_intake
from app.nemotron.local_intake import ContactFacts, IntakeError, contact_message
from app.nemotron.types import IntakeRequest, TimeRange, UserRecord
from fastapi import Request

from tests.stand_ins import DEMO_TEXT, FakeNano
from tests.test_pipeline_mock import events, make_client, start, wait_for

USERS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "backend" / "fixtures" / "users.json"
    ).read_text()
)
OWNER = UserRecord.model_validate(USERS["owner"])
CONTACT_PHONE = USERS["contacts"][0]["phone_e164"]
STRANGER = "+15555559999"
SLOT = datetime(2026, 11, 26, 9, 30, tzinfo=ZoneInfo("America/Chicago"))
INTAKE = IntakeRequest(
    care_type="dental cleaning",
    budget_max=150,
    insurance_carrier="Delta Dental",
    time_range=TimeRange(
        start="2026-11-23T00:00:00-06:00", end="2026-11-29T23:59:59-06:00"
    ),
    needs_ride=True,
    search_area="near home",
    dropped_fields=["mobility_details"],
)
FACTS = ContactFacts(
    "Mary",
    "Sarah",
    "dental cleaning",
    "Bright Smile Dental",
    SLOT,
    "123 Main St, Chicago, IL 60601",
)
TEMPLATE = texts.contact_request_message(
    "Sarah",
    "Mary",
    "dental cleaning",
    "Bright Smile Dental",
    SLOT,
    "123 Main St, Chicago, IL 60601",
)
# Values from the full record that must never reach the contact (product rule 4). "Mary" and "Sarah" are allowed.
PRIVATE = (
    "Johnson",
    "1948",
    "DEMO-0000",
    "Example Street",
    "5555550100",
    "Delta",
    "$",
    "150",
    "knee",
    "walking",
)


@pytest.fixture(autouse=True)
def metrics_file(monkeypatch, tmp_path):
    monkeypatch.setenv("METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    return tmp_path / "metrics.jsonl"


def write(model, **overrides):
    kwargs = {
        "relationship": "daughter",
        "request_text": DEMO_TEXT,
        "template": TEMPLATE,
        "model": model,
    }
    kwargs.update(overrides)
    return contact_message(OWNER, INTAKE, FACTS, **kwargs)


def test_model_message_passes_the_check_and_carries_only_the_four_facts(metrics_file):
    nano = FakeNano()
    written = write(nano)
    assert written.source == "nano" and written.violations == ()
    for fact in (
        "Bright Smile Dental",
        "9:30",
        "123 Main St",
        "YES",
        "NO",
        "Mary",
        "dental cleaning",
    ):
        assert fact in written.text
    for value in PRIVATE:
        assert value not in written.text, value
    # the model saw the whole record on the device: that is the point of writing the message locally
    record = nano.contact_records[0]
    assert (
        record["owner"]["insurance"]["member_id"] == "DEMO-0000-0000-0001"
        and record["spoken_request"] == DEMO_TEXT
    )
    row = json.loads(metrics_file.read_text().splitlines()[-1])
    assert (
        row["kind"] == "contact_message"
        and row["source"] == "nano"
        and row["chars"] == len(written.text)
    )
    assert not ({"text", "message", "utterance"} & set(row)), (
        "metrics never carry a person's words"
    )


@pytest.mark.parametrize(
    ("leaky", "kinds"),
    [
        (
            "Hi Sarah, Mary Johnson needs a ride to Bright Smile Dental at 9:30 AM, 123 Main St. Reply YES or NO.",
            {"owner_record_value"},
        ),
        (
            "Sarah: Mary (DOB 1948-03-14) has a dental cleaning at Bright Smile Dental, 9:30 AM, 123 Main St. Reply YES or NO.",
            {"identifier"},
        ),
        (
            "Mary's Delta Dental cleaning, $95, is at Bright Smile Dental 9:30 AM, 123 Main St. Can you drive? Reply YES or NO.",
            {"owner_record_value", "money"},
        ),
        (
            "Mary's knee makes walking hard. Bright Smile Dental, 9:30 AM, 123 Main St. Can you drive her? Reply YES or NO.",
            {"sensitive_term"},
        ),
        (
            "Mary has an appointment Thursday. Can you drive? Reply YES or NO.",
            {"missing_clinic", "missing_time", "missing_address"},
        ),
        (
            "Mary has a dental cleaning at Bright Smile Dental, 9:30 AM, 123 Main St. Please drive her.",
            {"missing_reply_instruction"},
        ),
        # the exact text Nano wrote in the first full browser run (#105): it must address Sarah, never open with Mary
        (
            "Mary Sarah can you drive Mary to Bright Smile Dental on Thu Nov 26, 9:30 AM at 123 Main St, Chicago, IL 60601? No accessible ride was found. Reply YES or NO.",
            {"salutation"},
        ),
        (
            "Hi there, Mary has a dental cleaning at Bright Smile Dental, 9:30 AM, 123 Main St. Can you drive? Reply YES or NO.",
            {"salutation"},
        ),
    ],
)
def test_a_model_message_that_leaks_or_drops_a_fact_is_refused_and_the_template_is_sent(
    leaky, kinds
):
    written = write(FakeNano(contact_message=leaky))
    assert written.source == "template" and written.text == TEMPLATE
    assert kinds <= set(written.violations), written.violations
    for value in PRIVATE:
        assert value not in written.text


class DownModel:
    name = "down"

    def complete_json(self, system, user, schema):
        raise IntakeError("Ollama is not reachable")


def test_template_is_used_when_the_model_is_down():
    written = write(DownModel())
    assert written == local_intake.ContactMessage(
        text=TEMPLATE, source="template", violations=("model_unavailable",)
    )


def test_the_template_itself_passes_the_check():
    assert (
        local_intake.contact_message_violations(
            TEMPLATE, OWNER, INTAKE, FACTS, DEMO_TEXT
        )
        == []
    )


# ---- the SMS reply path -------------------------------------------------------------------------------------------


def sms_route(client):
    """A test-only route that runs handle_contact_sms on the app's loop, standing in for the signed webhook (#80)."""

    async def inbound(request: Request) -> dict:
        form = await request.json()
        state = request.app.state
        return contact_replies.handle_contact_sms(
            state.engine,
            state.bus,
            state.pipeline,
            form["From"],
            form["Body"],
            form["MessageSid"],
        )

    client.app.add_api_route("/_test/sms", inbound, methods=["POST"])
    return lambda sender, body, sid: client.post(
        "/_test/sms", json={"From": sender, "Body": body, "MessageSid": sid}
    ).json()


@pytest.fixture
def waiting(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    task_id = start(client)
    wait_for(client, task_id, "awaiting_approval")
    client.post(
        f"/api/tasks/{task_id}/approve?viewer_id=mary",
        json={"actor_id": "mary", "decision": "approve", "idempotency_key": "ok"},
    )
    wait_for(client, task_id, "awaiting_contact")
    yield client, task_id, sms_route(client)
    client.__exit__(None, None, None)


def test_contact_message_in_the_pipeline_is_the_model_text_with_nothing_private(
    waiting,
):
    client, task_id, _ = waiting
    request = next(e for e in events(client, task_id) if e["type"] == "contact_request")
    assert (
        request["contact"] == "Sarah"
        and "Bright Smile Dental" in request["message"]
        and "123 Main St" in request["message"]
    )
    assert request["message"] != TEMPLATE, (
        "FakeNano's text passed the check, so the model wrote the message"
    )
    opening = request["message"][:40]
    assert "Sarah" in opening and not request["message"].startswith("Mary"), "the text is addressed to the contact"
    for value in PRIVATE:
        assert value not in request["message"], value


def test_yes_by_sms_confirms_the_ride_once_and_a_repeated_sid_replays(waiting):
    client, task_id, sms = waiting
    first = sms(CONTACT_PHONE, "Yes, I can drive her", "SMa")
    assert first == {"outcome": "ride_confirmed", "task_id": task_id}
    assert sms(CONTACT_PHONE, "Yes, I can drive her", "SMa") == first, (
        "T8: the same MessageSid replays"
    )
    wait_for(client, task_id, "completed")
    types = [e["type"] for e in events(client, task_id)]
    assert types.count("contact_reply") == 1 and types.count("ride_confirmed") == 1
    reply = next(e for e in events(client, task_id) if e["type"] == "contact_reply")
    assert reply == {
        **reply,
        "contact": "Sarah",
        "text": "Yes, I can drive her",
        "offer": {"can_drive": True, "pickup_time": reply["offer"]["pickup_time"]},
    }
    assert sms(CONTACT_PHONE, "yes", "SMb") == {"outcome": "no_task_waiting"}, (
        "after completion nothing waits"
    )


def test_no_by_sms_keeps_waiting_and_tells_the_owner_then_a_yes_confirms(waiting):
    client, task_id, sms = waiting
    assert sms(CONTACT_PHONE, "Sorry, I can't today", "SMn") == {
        "outcome": "declined",
        "task_id": task_id,
    }
    assert (
        client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"]
        == "awaiting_contact"
    )
    owner_events = events(client, task_id)
    assert [e["type"] for e in owner_events][-2:] == ["contact_reply", "task_updated"]
    note = owner_events[-1]
    assert (
        note["reason"] == "CONTACT_DECLINED"
        and note["status"] == "awaiting_contact"
        and "ride_confirmed" not in [e["type"] for e in owner_events]
    )
    assert "CONTACT_DECLINED" not in json.dumps(events(client, task_id, viewer="sarah"))
    assert sms(CONTACT_PHONE, "Maybe later", "SMm") == {
        "outcome": "unclear",
        "task_id": task_id,
    }
    assert len(events(client, task_id)) == len(owner_events), (
        "an unclear text changes nothing"
    )
    assert sms(CONTACT_PHONE, "ok yes I can", "SMy")["outcome"] == "ride_confirmed"
    wait_for(client, task_id, "completed")


def test_unknown_sender_is_refused_and_nothing_leaks(waiting):
    client, task_id, sms = waiting
    before = events(client, task_id)
    assert sms(STRANGER, "YES I will drive, send me the address", "SMs") == {
        "outcome": "UNVERIFIED_SENDER"
    }
    after = events(client, task_id)
    assert (
        len(after) == len(before) + 1
        and after[-1]["type"] == "task_updated"
        and after[-1]["reason"] == "UNVERIFIED_SENDER"
    )
    dumped = json.dumps(after) + json.dumps(events(client, task_id, viewer="sarah"))
    assert STRANGER not in dumped and "send me the address" not in dumped
    assert "UNVERIFIED_SENDER" not in json.dumps(
        events(client, task_id, viewer="sarah")
    ), "the owner's note only"
    assert (
        client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"]
        == "awaiting_contact"
    )
    assert sms(STRANGER, "YES", "SMs") == {"outcome": "UNVERIFIED_SENDER"} and len(
        events(client, task_id)
    ) == len(after), "replayed, not repeated"


def test_interpret_prefers_a_decline_when_both_words_appear():
    assert contact_replies.interpret("Yes but I can't make it") == "no"
    assert contact_replies.interpret("YES") == "yes"
    assert contact_replies.interpret("I'll drive") == "yes"
    assert contact_replies.interpret("What time?") is None
