"""Mock adapter contracts and failure cases; sockets are forbidden in this suite."""

import json
import socket
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from integrations import google_calendar as calendar
from integrations import google_distance as distance
from integrations import google_places as places
from integrations import sms_twilio as sms
from integrations import transport_sim as transport
from integrations.fixtures import read_fixture
from integrations.types import (
    Booking,
    CalendarReceipt,
    CallSpec,
    Clinic,
    Distance,
    InboundSms,
    IntakeRequest,
    MessageReceipt,
    TransportOptions,
    Window,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    for name, value in {
        "CALENDAR_MODE": "mock",
        "PLACES_MODE": "fixture",
        "SMS_MODE": "mock",
        "TRANSPORT_MODE": "fixture",
        "DEMO_PHONE_ALLOWLIST": "+15555550100,+15555550101",
    }.items():
        monkeypatch.setenv(name, value)

    def no_network(*args, **kwargs):
        pytest.fail("Mock adapter attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)


@pytest.fixture
def booking():
    reply = read_fixture("receptionists.json")["receptionists"][0]
    return Booking(
        clinic="Bright Smile Dental",
        slot_start=reply["result"]["slot_start"],
        slot_end=reply["result"]["slot_end"],
        price="$95",
        status="confirmed",
        confirmation_ref="mock-confirmation",
    )


def test_calendar_reads_windows_and_clips_to_requested_range():
    windows = calendar.free_windows(
        "mary", "2026-11-24T15:00:00-06:00", "2026-11-26T10:00:00-06:00"
    )
    assert len(windows) == 2
    assert all(isinstance(window, Window) for window in windows)
    assert windows[0].start.hour == 15
    assert windows[1].end.hour == 10


def test_calendar_empty_range_and_unknown_owner():
    assert (
        calendar.free_windows("mary", "2026-12-01T00:00:00Z", "2026-12-02T00:00:00Z")
        == []
    )
    with pytest.raises(Exception, match="no windows"):
        calendar.free_windows("unknown", "2026-12-01T00:00:00Z", "2026-12-02T00:00:00Z")


def test_calendar_receipt_is_simulated_private_and_stable(booking):
    first = calendar.create_event("mary", booking, "demo:calendar")
    assert isinstance(first, CalendarReceipt)
    assert first == calendar.create_event("mary", booking, "demo:calendar")
    assert first != calendar.create_event("mary", booking, "other:calendar")
    assert first.simulated and first.title == "Appointment"
    assert first.visibility == "private" and first.reminder_minutes == 1440


@pytest.mark.parametrize("status", ["tentative", "rejected"])
def test_calendar_refuses_unconfirmed_booking(booking, status):
    booking.status = status
    with pytest.raises(Exception, match="confirmed"):
        calendar.create_event("mary", booking, "demo:calendar")


def test_places_reads_fixture_and_respects_limit():
    clinics = places.find_clinics("dental cleaning", "Chicago, IL", limit=2)
    assert len(clinics) == 2
    assert all(isinstance(clinic, Clinic) and clinic.simulated for clinic in clinics)
    assert clinics[0].name == "Bright Smile Dental"
    assert places.find_clinics("dental cleaning", "near home", limit=0) == []
    assert places.find_clinics("eye exam", "Chicago, IL") == []
    assert places.find_clinics("dental cleaning", "different city") == []


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_places_rejects_invalid_limit(limit):
    with pytest.raises(RuntimeError, match="limit"):
        places.find_clinics("dental cleaning", "Chicago, IL", limit)


def test_distances_join_by_place_id_and_keep_input_order():
    clinics = places.find_clinics("dental cleaning", "near home")
    home = read_fixture("users.json")["owner"]["home"]
    routes = distance.drive(home, list(reversed(clinics)))
    assert all(isinstance(route, Distance) and route.simulated for route in routes)
    assert [route.miles for route in routes] == [3.4, 0.6, 1.2]
    assert [route.minutes for route in routes] == [14, 4, 6]
    assert distance.drive(home["address"], []) == []
    with pytest.raises(Exception, match="home"):
        distance.drive("other origin", clinics)
    clinics[0].place_id = "unknown"
    with pytest.raises(Exception, match="no route"):
        distance.drive(home, clinics)


def test_sms_returns_simulation_without_publishing_or_logging(capsys):
    receipt = sms.send("+15555550101", "Demo ride request", "demo:contact")
    assert isinstance(receipt, MessageReceipt) and receipt.simulated
    assert receipt == sms.send("+15555550101", "Demo ride request", "demo:contact")
    assert receipt != sms.send("+15555550101", "Demo ride request", "other:contact")
    event = receipt.dashboard_event("contact")
    assert event["sms_contact"] == "Demo ride request" and event["simulated"]
    schema = json.loads((ROOT / "shared" / "events.schema.json").read_text())
    jsonschema.validate(event, schema)
    jsonschema.validate(receipt.dashboard_event("owner"), schema)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("phone", ["+15555550999", "555-0100", ""])
def test_sms_rejects_unknown_or_malformed_outbound_number(phone):
    with pytest.raises(Exception, match="UNVERIFIED_SENDER"):
        sms.send(phone, "Synthetic test", "demo:send")


def test_inbound_returns_synthetic_role_and_correlation():
    result = sms.parse_inbound(
        {
            "From": "+15555550101",
            "Body": "I can drive",
            "MessageSid": "mock-inbound",
            "task_id": "demo",
        }
    )
    assert isinstance(result, InboundSms) and result.simulated
    assert result.role == "contact" and result.correlation == "demo"
    assert (
        sms.parse_inbound(
            {"From": "+15555550100", "Body": "YES", "MessageSid": "mock-approval"}
        ).role
        == "owner"
    )


def test_inbound_unknown_sender_is_rejected_even_with_fake_role():
    with pytest.raises(Exception, match="UNVERIFIED_SENDER"):
        sms.parse_inbound(
            {
                "From": "+15555550999",
                "Body": "YES",
                "MessageSid": "mock-unknown",
                "role": "owner",
            }
        )


def test_inbound_allowlisted_but_unmapped_sender_rejected(monkeypatch):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550999")
    with pytest.raises(Exception, match="no synthetic"):
        sms.parse_inbound({"From": "+15555550999", "Body": "YES", "MessageSid": "mock"})


def test_transport_uses_unavailable_fixture_and_event_schema(booking):
    result = transport.check(booking, {"accessible": True})
    assert isinstance(result, TransportOptions)
    assert result.model_dump() == {
        "available": False,
        "reason": "UNAVAILABLE_ACCESSIBLE_RIDE",
        "simulated": True,
    }
    schema = json.loads((ROOT / "shared" / "events.schema.json").read_text())
    jsonschema.validate(result.dashboard_event(), schema)


def test_time_models_reject_naive_or_reversed_ranges():
    with pytest.raises(ValidationError):
        Window(start="2026-11-24T13:00:00", end="2026-11-24T17:00:00")
    with pytest.raises(ValidationError):
        Window(start="2026-11-24T17:00:00Z", end="2026-11-24T13:00:00Z")


def test_transport_accepts_tentative_booking(booking):
    booking.status = "tentative"
    assert (
        transport.check(booking, {"accessible": True}).reason
        == "UNAVAILABLE_ACCESSIBLE_RIDE"
    )
    with pytest.raises(RuntimeError, match="confirmed"):
        calendar.create_event("mary", booking, "tentative:calendar")


def test_transport_refuses_rejected_booking(booking):
    booking.status = "rejected"
    with pytest.raises(RuntimeError, match="rejected"):
        transport.check(booking, {"accessible": True})


def test_call_spec_accepts_null_search_area_from_intake():
    intake = IntakeRequest(
        care_type="dental cleaning",
        time_range={
            "start": "2026-11-24T13:00:00-06:00",
            "end": "2026-11-24T17:00:00-06:00",
        },
        needs_ride=True,
        search_area=None,
    )
    schema = json.loads((ROOT / "shared" / "intake_request.schema.json").read_text())
    jsonschema.validate(intake.model_dump(mode="json"), schema)
    call = CallSpec(
        clinic=places.find_clinics("dental cleaning", "near home")[0],
        request=intake,
        windows=[],
        call_id="mock-null-area",
    )
    assert call.request.search_area is None
