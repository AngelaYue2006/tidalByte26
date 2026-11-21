"""Stable Calendar event identity, demo address resolution and receipt verification."""

import hashlib
import json
from datetime import UTC, datetime

from integrations.fixtures import read_fixture
from integrations.types import Booking, CalendarReceipt


def event_body(owner_id, booking: Booking, idempotency_key, timezone) -> dict:
    clinics = read_fixture("clinics.json")["clinics"]
    matches = [c for c in clinics if c["name"].casefold() == booking.clinic.casefold()]
    if len(matches) != 1:
        raise RuntimeError("Calendar booking address is unavailable for this clinic")
    address = matches[0]["address"]
    identity = json.dumps([owner_id, idempotency_key], separators=(",", ":"))
    event_id = "lifeline" + hashlib.sha256(identity.encode()).hexdigest()
    body = {
        "id": event_id,
        "summary": "Appointment",
        "status": "confirmed",
        "description": f"Clinic: {booking.clinic}\nAddress: {address}",
        "location": address,
        "start": {
            "dateTime": booking.slot_start.astimezone(timezone).isoformat(),
            "timeZone": str(timezone),
        },
        "end": {
            "dateTime": booking.slot_end.astimezone(timezone).isoformat(),
            "timeZone": str(timezone),
        },
        "visibility": "private",
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 1440}],
        },
    }
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    body["extendedProperties"] = {"private": {"lifeline_payload_hash": fingerprint}}
    return body


def _instant(value: str):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("Timezone required")
    return instant.astimezone(UTC)


def verified_receipt(event: dict, expected: dict) -> CalendarReceipt:
    fields = (
        "id",
        "summary",
        "status",
        "description",
        "location",
        "visibility",
        "reminders",
    )
    matches = all(event.get(field) == expected[field] for field in fields)
    fingerprint = (
        event.get("extendedProperties", {})
        .get("private", {})
        .get("lifeline_payload_hash")
    )
    matches = (
        matches
        and fingerprint
        == expected["extendedProperties"]["private"]["lifeline_payload_hash"]
    )
    try:
        for field in ("start", "end"):
            matches = matches and _instant(event[field]["dateTime"]) == _instant(
                expected[field]["dateTime"]
            )
    except (KeyError, TypeError, ValueError):
        matches = False
    if not matches:
        raise RuntimeError(
            "Calendar event does not match the confirmed booking and idempotency key"
        )
    return CalendarReceipt(event_id=expected["id"], simulated=False)
