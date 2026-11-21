"""Subtract vendor busy intervals in UTC, then display in the configured timezone."""

from datetime import UTC

from integrations.types import Window


def available_windows(requested: Window, response: dict, timezone) -> list[Window]:
    calendar = response.get("calendars", {}).get("primary")
    if (
        not isinstance(calendar, dict)
        or calendar.get("errors")
        or "busy" not in calendar
    ):
        raise RuntimeError("Calendar availability is missing or returned an error")
    start, end = requested.start.astimezone(UTC), requested.end.astimezone(UTC)
    try:
        busy = [Window(**item) for item in calendar["busy"]]
    except (ValueError, TypeError):
        raise RuntimeError("Calendar returned invalid busy intervals") from None
    clipped = sorted(
        (max(start, w.start.astimezone(UTC)), min(end, w.end.astimezone(UTC)))
        for w in busy
        if w.end.astimezone(UTC) > start and w.start.astimezone(UTC) < end
    )
    free = []
    cursor = start
    for busy_start, busy_end in clipped:
        if cursor < busy_start:
            free.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if cursor < end:
        free.append((cursor, end))
    # ISO offsets preserve ordering across a DST fold even when local clocks reverse.
    return [
        Window(
            start=a.astimezone(timezone).isoformat(),
            end=b.astimezone(timezone).isoformat(),
        )
        for a, b in free
    ]
