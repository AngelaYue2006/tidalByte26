"""Mock and live Google Calendar adapters; approval and receipt storage stay backend-owned."""

import hashlib
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from integrations.calendar_event import event_body, verified_receipt
from integrations.calendar_google_api import CalendarClient
from integrations.calendar_windows import available_windows
from integrations.fixtures import read_fixture
from integrations.types import Booking, CalendarReceipt, Window


def _mode():
    mode = os.getenv("CALENDAR_MODE", "mock")
    if mode not in {"mock", "live"}:
        raise RuntimeError("CALENDAR_MODE must be mock or live")
    return mode


def _live_context(owner_id):
    if owner_id != read_fixture("users.json")["owner"]["id"]:
        raise RuntimeError("Calendar live mode supports only the demo owner")
    try:
        return ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago"))
    except (ZoneInfoNotFoundError, ValueError):
        raise RuntimeError(
            "APP_TIMEZONE must name an installed IANA timezone"
        ) from None


def free_windows(owner_id, start_iso, end_iso) -> list[Window]:
    mode = _mode()
    requested = Window(start=start_iso, end=end_iso)
    if mode == "live":
        timezone = _live_context(owner_id)
        body = {
            "timeMin": requested.start.isoformat(),
            "timeMax": requested.end.isoformat(),
            "timeZone": str(timezone),
            "items": [{"id": "primary"}],
        }
        with CalendarClient() as client:
            return available_windows(requested, client.free_busy(body), timezone)
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
    mode = _mode()
    if not owner_id or not idempotency_key:
        raise RuntimeError("Calendar owner and idempotency key are required")
    if booking.status != "confirmed":
        raise RuntimeError("Calendar event requires a confirmed booking")
    if mode == "live":
        timezone = _live_context(owner_id)
        body = event_body(owner_id, booking, idempotency_key, timezone)
        with CalendarClient() as client:
            event = client.insert_event(body)
            if event is None:  # Google 409: the deterministic ID already exists.
                event = client.get_event(body["id"])
        return verified_receipt(event, body)
    identity = f"{owner_id}:{idempotency_key}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return CalendarReceipt(event_id=f"mock-calendar-{digest}", simulated=True)
