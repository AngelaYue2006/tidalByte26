"""Live Calendar behavior with an in-memory fake vendor, never real calendar writes."""

import copy
import re
import socket

import pytest

from integrations import google_calendar as calendar
from integrations.types import Booking


class FakeCalendar:
    def __init__(self):
        self.availability = {"calendars": {"primary": {"busy": []}}}
        self.queries = []
        self.events = {}
        self.inserts = 0
        self.lookups = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def free_busy(self, body):
        self.queries.append(body)
        return self.availability

    def insert_event(self, body):
        self.inserts += 1
        if body["id"] in self.events:
            return None
        event = copy.deepcopy(body)
        event["status"] = "confirmed"
        self.events[body["id"]] = event
        return event

    def get_event(self, event_id):
        self.lookups += 1
        return self.events[event_id]


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.setenv("CALENDAR_MODE", "live")
    monkeypatch.setenv("APP_TIMEZONE", "America/Chicago")
    fake = FakeCalendar()
    monkeypatch.setattr(calendar, "CalendarClient", lambda: fake, raising=False)

    def deny_network(*args, **kwargs):
        pytest.fail("Calendar unit test attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    return fake


@pytest.fixture
def booking():
    return Booking(
        clinic="Bright Smile Dental",
        slot_start="2026-11-26T15:30:00Z",
        slot_end="2026-11-26T16:30:00Z",
        price="$95",
        status="confirmed",
        confirmation_ref="synthetic-confirmation",
    )


def test_free_windows_merge_overlap_and_clip_busy_ranges(vendor):
    vendor.availability["calendars"]["primary"]["busy"] = [
        {"start": "2026-11-24T15:30:00Z", "end": "2026-11-24T17:00:00Z"},
        {"start": "2026-11-24T13:00:00Z", "end": "2026-11-24T14:30:00Z"},
        {"start": "2026-11-24T15:00:00Z", "end": "2026-11-24T16:00:00Z"},
        {"start": "2026-11-24T22:00:00Z", "end": "2026-11-25T00:00:00Z"},
    ]
    windows = calendar.free_windows(
        "mary", "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z"
    )
    assert [(w.start.isoformat(), w.end.isoformat()) for w in windows] == [
        ("2026-11-24T08:30:00-06:00", "2026-11-24T09:00:00-06:00"),
        ("2026-11-24T11:00:00-06:00", "2026-11-24T16:00:00-06:00"),
    ]
    assert vendor.queries[0]["timeZone"] == "America/Chicago"
    assert vendor.queries[0]["items"] == [{"id": "primary"}]


def test_empty_busy_list_and_fully_busy_range(vendor):
    start, end = "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z"
    assert len(calendar.free_windows("mary", start, end)) == 1
    vendor.availability["calendars"]["primary"]["busy"] = [{"start": start, "end": end}]
    assert calendar.free_windows("mary", start, end) == []


def test_timezone_conversion_handles_daylight_saving_fold(vendor):
    windows = calendar.free_windows(
        "mary", "2026-11-01T06:30:00Z", "2026-11-01T07:15:00Z"
    )
    assert windows[0].start.isoformat() == "2026-11-01T01:30:00-05:00"
    assert windows[0].end.isoformat() == "2026-11-01T01:15:00-06:00"
    assert windows[0].start < windows[0].end


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}},
        {"calendars": {"primary": {}}},
    ],
)
def test_vendor_errors_do_not_become_free_time(vendor, response):
    vendor.availability = response
    with pytest.raises(RuntimeError, match="Calendar"):
        calendar.free_windows("mary", "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z")


def test_invalid_input_and_unknown_owner_never_query_vendor(vendor, monkeypatch):
    with pytest.raises(ValueError):
        calendar.free_windows("mary", "2026-11-24T14:00:00Z", "2026-11-24T13:00:00Z")
    with pytest.raises(RuntimeError, match="owner"):
        calendar.free_windows("unknown", "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z")
    monkeypatch.setenv("APP_TIMEZONE", "invalid/timezone")
    with pytest.raises(RuntimeError, match="APP_TIMEZONE"):
        calendar.free_windows("mary", "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z")
    assert vendor.queries == []


def test_create_event_is_private_with_clinic_address_and_reminder(vendor, booking):
    receipt = calendar.create_event("mary", booking, "demo:calendar")
    event = vendor.events[receipt.event_id]
    assert receipt.simulated is False
    assert re.fullmatch("[0-9a-v]{5,1024}", receipt.event_id)
    assert event["summary"] == "Appointment" and event["visibility"] == "private"
    assert "Bright Smile Dental" in event["description"]
    assert "123 Main St" in event["description"]
    assert event["start"] == {
        "dateTime": "2026-11-26T09:30:00-06:00",
        "timeZone": "America/Chicago",
    }
    assert event["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 1440}],
    }
    assert "attendees" not in event


def test_retries_reuse_vendor_event_and_validate_conflicting_key(vendor, booking):
    first = calendar.create_event("mary", booking, "demo:calendar")
    assert calendar.create_event("mary", booking, "demo:calendar") == first
    assert len(vendor.events) == 1 and vendor.lookups == 1
    changed = booking.model_copy(deep=True)
    changed.slot_end = changed.slot_end.replace(hour=17)
    with pytest.raises(RuntimeError, match="different|match"):
        calendar.create_event("mary", changed, "demo:calendar")
    assert len(vendor.events) == 1
    second = calendar.create_event("mary", booking, "other:calendar")
    assert second.event_id != first.event_id and len(vendor.events) == 2


@pytest.mark.parametrize(
    "field,value",
    [("status", "cancelled"), ("visibility", "public"), ("summary", "Changed")],
)
def test_modified_existing_event_is_not_a_valid_receipt(vendor, booking, field, value):
    receipt = calendar.create_event("mary", booking, "demo:calendar")
    vendor.events[receipt.event_id][field] = value
    with pytest.raises(RuntimeError, match="match|confirmed"):
        calendar.create_event("mary", booking, "demo:calendar")


@pytest.mark.parametrize("status", ["tentative", "rejected"])
def test_unconfirmed_booking_never_inserts(vendor, booking, status):
    booking.status = status
    with pytest.raises(RuntimeError, match="confirmed"):
        calendar.create_event("mary", booking, "demo:calendar")
    assert vendor.inserts == 0


def test_unknown_clinic_and_empty_key_never_insert(vendor, booking):
    booking.clinic = "Unknown clinic"
    with pytest.raises(RuntimeError, match="address"):
        calendar.create_event("mary", booking, "demo:calendar")
    with pytest.raises(RuntimeError, match="key"):
        calendar.create_event("mary", booking, "")
    assert vendor.inserts == 0


def test_retry_accepts_equivalent_vendor_utc_timestamp(vendor, booking):
    receipt = calendar.create_event("mary", booking, "demo:calendar")
    vendor.events[receipt.event_id]["start"]["dateTime"] = "2026-11-26T15:30:00Z"
    assert calendar.create_event("mary", booking, "demo:calendar") == receipt


def test_unknown_mode_fails_before_any_query(vendor, monkeypatch):
    monkeypatch.setenv("CALENDAR_MODE", "invalid")
    with pytest.raises(RuntimeError, match="CALENDAR_MODE"):
        calendar.free_windows("mary", "2026-11-24T14:00:00Z", "2026-11-24T23:00:00Z")
    assert vendor.queries == []


def test_live_clinic_outside_fixture_uses_booked_address(vendor, booking):
    booking = Booking.model_validate(
        {
            **booking.model_dump(),
            "clinic": "New live clinic",
            "address": "42 Selected Clinic Avenue",
        }
    )
    receipt = calendar.create_event("mary", booking, "live:calendar")
    event = vendor.events[receipt.event_id]
    assert event["location"] == booking.address
    assert "42 Selected Clinic Avenue" in event["description"]
    assert "New live clinic" in event["description"]


def test_selected_address_wins_over_fixture_name_collision(vendor, booking):
    booking = Booking.model_validate(
        {**booking.model_dump(), "address": "99 Actual Clinic Road"}
    )
    receipt = calendar.create_event("mary", booking, "collision:calendar")
    event = vendor.events[receipt.event_id]
    assert event["location"] == "99 Actual Clinic Road"
    assert "123 Main St" not in event["description"]


@pytest.mark.parametrize("address", ["", "   "])
def test_explicit_empty_address_never_falls_back_to_fixture(vendor, booking, address):
    booking = Booking.model_validate({**booking.model_dump(), "address": address})
    with pytest.raises(RuntimeError, match="address"):
        calendar.create_event("mary", booking, "empty:calendar")
    assert vendor.inserts == 0
