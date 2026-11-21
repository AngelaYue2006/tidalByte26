"""Google Calendar mock facts; live service implementation belongs to #28."""

import hashlib
import os

from integrations.fixtures import read_fixture
from integrations.types import Booking, CalendarReceipt, Window


def _require_mock():
    if os.getenv("CALENDAR_MODE", "mock") != "mock":
        raise RuntimeError(
            "Calendar live mode is not implemented; use CALENDAR_MODE=mock"
        )


def free_windows(owner_id, start_iso, end_iso) -> list[Window]:
    _require_mock()
    requested = Window(start=start_iso, end=end_iso)
    fixture = read_fixture("free_windows.json")
    if owner_id != fixture["owner_id"]:
        raise RuntimeError("Calendar fixture has no windows for this owner")
    result = []
    for item in fixture["windows"]:
        window = Window(start=item["start"], end=item["end"])
        start, end = max(requested.start, window.start), min(requested.end, window.end)
        if start < end:
            result.append(Window(start=start, end=end))
    return result


def create_event(owner_id, booking: Booking, idempotency_key) -> CalendarReceipt:
    _require_mock()
    if not owner_id or not idempotency_key:
        raise RuntimeError("Calendar owner and idempotency key are required")
    if booking.status != "confirmed":
        raise RuntimeError("Calendar event requires a confirmed booking")
    # Stable fake identity, no persistence. Backend approval and receipt checks still apply.
    identity = f"{owner_id}:{idempotency_key}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return CalendarReceipt(event_id=f"mock-calendar-{digest}", simulated=True)
