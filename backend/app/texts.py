"""Every sentence the pipeline shows or sends: request chips, calendar card text, SMS texts and the contact message template.

The contact message is a template until #23 has Nano write it on the device; it already carries only the contact's
scope: clinic, time, address and the ride need.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.ranking import money, slot_label


def chips(care_type: str, budget_max: float | None, carrier: str | None, windows: list, time_range: tuple[datetime, datetime] | None = None) -> list[str]:
    """The request chips. `time_range` is the requested range, so a window that covers all of it reads "all week"."""
    out = [care_type[:1].upper() + care_type[1:]]
    if budget_max is not None:
        out.append(f"Max {money(budget_max)}")
    if carrier:
        out.append(carrier)
    if windows:
        labels = []
        for w in windows:
            label = window_chip(w.start, w.end, time_range)
            if label not in labels:
                labels.append(label)
        out.append("Free: " + ", ".join(labels))
    out.append("!Processed on device")
    return out


def window_chip(start: datetime, end: datetime, time_range: tuple[datetime, datetime] | None = None) -> str:
    """One free window as a chip: "Thu am" inside one part of a day, "Tue–Sun" when it crosses midnight, "all week" when
    the one window covers the whole requested range. Live freeBusy returns the week minus the busy blocks, so its windows
    are multi-day spans; the fixture's are single mornings and afternoons (#107)."""
    if time_range is not None and start <= time_range[0] and end >= time_range[1]:
        return "all week"
    last_day = (end - timedelta(microseconds=1)).date()  # a window ending exactly at midnight belongs to the day before
    if last_day > start.date():
        return f"{start:%a}–{end - timedelta(microseconds=1):%a}"
    return f"{start:%a} {'am' if start.hour < 12 else 'pm'}"


def clock(when: datetime) -> str:
    return f"{when.hour % 12 or 12}:{when:%M} {when:%p}"


def day_and_time(when: datetime) -> str:
    return f"{when:%a %b} {when.day}, {clock(when)}"


def calendar_card(start: datetime, end: datetime, address: str) -> str:
    return f"Appointment · {start:%a %b} {start.day} · {start.hour % 12 or 12}:{start:%M}–{clock(end)} · {address} · private · reminder 1 day before"


def booked_sms(clinic: str, start: datetime, price: float, carrier: str | None) -> str:
    with_carrier = f" with {carrier}" if carrier else ""
    return f"LifeLine: Booked {clinic}, {day_and_time(start)}, {money(price)}{with_carrier}. Reply C to cancel."


def tentative_sms(clinic: str, start: datetime) -> str:
    return f"LifeLine: {clinic} will call back to confirm {day_and_time(start)}. Nothing is on your calendar yet."


def approval_sms(clinic: str, start: datetime, price: float) -> str:
    return f"LifeLine: Best option is {clinic}, {slot_label(start)} for {money(price)}. Reply YES to book, or tap Approve."


def approval_reminder_sms(clinic: str, start: datetime, price: float) -> str:
    return f"LifeLine reminder: {clinic}, {slot_label(start)} for {money(price)} is still open. Reply YES to book or NO to cancel."


def contact_request_message(contact_first_name: str, owner_first_name: str, care_type: str, clinic: str, start: datetime, address: str) -> str:
    """The ride request as the contact reads it: addressed to them, then the four facts, then the question."""
    return (
        f"LifeLine: {contact_first_name}, {owner_first_name} has a {care_type} at {clinic}, {day_and_time(start)}, {address}. "
        f"No accessible ride is available. Can you drive {owner_first_name}? Reply YES or NO."
    )


def ride_confirmed_sms_user(driver: str, clinic: str, start: datetime) -> str:
    return f"LifeLine: {driver} will drive you to {clinic} on {day_and_time(start)}."


def ride_confirmed_sms_contact(owner_first_name: str, clinic: str, start: datetime) -> str:
    return f"LifeLine: Thank you. Ride confirmed for {owner_first_name}'s appointment at {clinic}, {day_and_time(start)}."


def no_ride_needed_sms_contact(owner_first_name: str, clinic: str, start: datetime, address: str) -> str:
    return f"LifeLine: Appointment booked for {owner_first_name} — {clinic}, {day_and_time(start)}, {address}."


def contact_declined_sms_user(contact_first_name: str, clinic: str, start: datetime) -> str:
    return f"LifeLine: {contact_first_name} can't drive you to {clinic} on {day_and_time(start)}. We're still looking for a ride and will text you."


def contact_declined_sms_contact(owner_first_name: str) -> str:
    return f"LifeLine: Thanks for letting us know. We'll keep looking for a ride for {owner_first_name}."

