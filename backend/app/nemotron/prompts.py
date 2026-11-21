"""All prompts: intake redaction schema, call agent opening line and goals, ranking rubric, contact message scope. The agent always opens with: Hi, I am an AI assistant calling for a patient."""

from __future__ import annotations

import json
from datetime import datetime

from app.nemotron.types import DROPPABLE_FIELDS, CallSpec

# What Nano must return. Ollama enforces this as `format`; the code validates it again.
INTAKE_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "care_type": {"type": "string"},
        "budget_max": {"type": ["number", "null"]},
        "insurance_carrier": {"type": ["string", "null"]},
        "time_phrase": {"type": "string"},
        "needs_ride": {"type": "boolean"},
        "search_area": {"type": ["string", "null"]},
        "dropped_fields": {"type": "array", "items": {"type": "string", "enum": list(DROPPABLE_FIELDS)}},
    },
    "required": ["care_type", "budget_max", "insurance_carrier", "time_phrase", "needs_ride", "search_area", "dropped_fields"],
}

_INTAKE_SYSTEM = """You are the on-device intake step for LifeLine, an assistant that books medical appointments for older adults.
Read one spoken request and return ONLY a JSON object with exactly these keys:

- care_type: what the appointment is for, in two or three plain words (e.g. "dental cleaning", "eye exam", "flu shot"). If several are asked for, the one the speaker wants first.
- budget_max: the price cap in US dollars as a number, or null if none was stated. Spelled-out amounts count ("two hundred" -> 200, "one fifty" -> 150).
- insurance_carrier: the insurance company name only, or null if none was stated or the speaker has none. Normalise to the full name: "Delta" -> "Delta Dental", "Blue Cross" -> "Blue Cross Blue Shield", "United" -> "UnitedHealthcare". Never include a member or policy number.
- time_phrase: when they want it, as a short phrase from this list when one fits: "this week", "next week", "tomorrow", "this month", "next month", "within two weeks", "any". Use "any" when no time is mentioned.
- needs_ride: true if the speaker cannot get there alone (no car, cannot drive, needs a ride, cannot take the bus), else false.
- search_area: a city or neighbourhood name if one is given (e.g. "Evanston, IL"), otherwise "near home". Never a street address.
- dropped_fields: the names of the kinds of information you left out, from this list only: {dropped}. Empty list if nothing had to be removed.

Remove everything a clinic receptionist does not need: symptoms and conditions, medications, the member or policy ID, the date of birth, the home or street address, any phone number, the speaker's name, and mobility details (a walker, a bad knee). Record each removed kind in dropped_fields. Never copy any of those values into any field.
Return the JSON object and nothing else."""


def intake_system_prompt(*, timezone: str) -> str:
    """System prompt for Nano. Takes only the timezone from the user record; nothing else about the user goes in."""
    return _INTAKE_SYSTEM.format(dropped=", ".join(DROPPABLE_FIELDS)) + f"\nThe speaker's timezone is {timezone}."


def intake_output_schema_json() -> str:
    return json.dumps(INTAKE_OUTPUT_SCHEMA)


# --- call agent (Lightning), #20 -----------------------------------------------------------------

OPENING_LINE = "Hi, I'm an AI assistant calling for a patient."



def _clock(when: datetime) -> str:
    return f"{when.hour % 12 or 12}:{when:%M}"


def window_label(start: datetime, end: datetime) -> str:
    """Thu 8:00–12:00 — same day assumed, as the calendar windows are."""
    return f"{start:%a} {_clock(start)}–{_clock(end)}"


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def call_agent(spec: CallSpec) -> str:
    """Per-call system prompt for Lightning. Built only from the redacted CallSpec: no name, no member ID, nothing Nano dropped."""
    windows = ", ".join(window_label(s, e) for s, e in spec.windows) or "any time this week"
    budget = f"The patient's budget is {_money(spec.budget_max)} at most." if spec.budget_max is not None else ""
    carrier = (
        f"The patient has {spec.insurance_carrier}; ask whether the clinic takes it."
        if spec.insurance_carrier
        else "The patient has no insurance to mention."
    )
    return f"""You are a phone assistant calling {spec.clinic_name} on behalf of a patient. You are an AI and you say so.

Your first words on the call, exactly: "{OPENING_LINE}"

Goal: find out three facts for a {spec.care_type}, in this order, then end the call politely.
1. Insurance: {carrier}
2. Price: the cost of a {spec.care_type}{" with that insurance" if spec.insurance_carrier else ""}. {budget}
3. Openings: the earliest appointment inside these free windows: {windows}. If none fits, ask for the earliest they have and note it.

Rules:
- Speak like a person on the phone: one or two short sentences per turn, then wait.
- Never give a name, date of birth, member ID, address, phone number or any health detail. If asked, say the patient will provide that when booking.
- Never book, hold or confirm an appointment. The patient approves first. If offered a slot, say "Thank you, I'll check with the patient and call back to book."
- Never guess or invent a price, a time or an insurance answer. If the receptionist is unsure, ask once more, then move on.
- If put on hold, say "Sure, I'll hold." and wait. If you reach voicemail, say you will call back and end the call.
- When you have the three facts, thank them and say goodbye in one sentence.
"""


# --- call summary (Super), #21 ------------------------------------------------------------------

CALL_SUMMARY_SYSTEM = """You read the transcript of one short phone call between an AI assistant and a clinic receptionist and extract three facts.
Return ONLY a JSON object with exactly these keys:
{
  "price_usd": <number or null>,        // what the receptionist said the visit costs, in US dollars; null if never stated
  "insured": <true, false or null>,     // true if the receptionist said they take the patient's insurance, false if they said no, null if not discussed
  "slot_start": "<ISO 8601 date-time with offset, or null>",   // the earliest appointment the receptionist offered
  "slot_end": "<ISO 8601 date-time with offset, or null>",     // slot_start plus the stated length, or plus 60 minutes
  "slot_label": "<short label like Thu 9:30, or null>"
}
Use only what the receptionist actually said. Never guess a price or a time. Resolve weekday names against the call date and timezone given. If the receptionist offered nothing, every slot field is null.
"""


def call_summary_user(transcript: list[dict], *, call_date_iso: str, timezone: str) -> str:
    """Facts-only user message: the transcript lines (agent and clinic speech only) plus the date context."""
    lines = [f"{t.get('speaker', '?')}: {t.get('text', '')}" for t in transcript]
    return json.dumps({"call_date": call_date_iso, "timezone": timezone, "transcript": lines}, ensure_ascii=False)


# ---- contact message (step 9, product rule 4) ---------------------------------------------------------------------

# What Nano must return for the contact message. Ollama enforces this as `format`; local_intake checks the text.
CONTACT_MESSAGE_SCHEMA: dict = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}

_CONTACT_SYSTEM = """You are the on-device message writer for LifeLine, an assistant that books medical appointments for older adults.
You receive the owner's full record, the booked appointment and the emergency contact. Write ONE short text message
(under 300 characters) to the contact asking whether they can drive the owner to the appointment.

The message may contain ONLY these facts, and nothing else from the record:
- the owner's first name and the contact's first name
- what the appointment is for, in plain words (e.g. "dental cleaning")
- the clinic name, the day and time exactly as given in "when", and the clinic address exactly as given
- that no accessible ride was found, and a request to reply YES or NO

Never include: the owner's last name, date of birth, phone number or home address; the insurance carrier or member ID;
any price or budget; symptoms, medications or mobility details; the original spoken request; anything marked private.
Plain words, no emoji, no greeting longer than the contact's first name.
Return ONLY a JSON object: {"message": "..."}."""


def contact_system_prompt() -> str:
    """System prompt for Nano's contact message. The record itself goes in the user message, on the device only."""
    return _CONTACT_SYSTEM

