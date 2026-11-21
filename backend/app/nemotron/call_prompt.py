"""Per-call system prompt for Nemotron Lightning, the live call agent.

Built only from the redacted IntakeRequest, the free windows and the clinic row: no name, no member ID,
no symptoms, nothing Nano dropped. Lives here while #10 holds prompts.py; move it there once #10 merges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

OPENING_LINE = "Hi, I'm an AI assistant calling for a patient."


@dataclass(frozen=True)
class CallSpec:
    """What the agent may know on one call. Everything here is already redacted."""

    call_id: str
    task_id: str
    clinic_name: str
    care_type: str
    budget_max: float | None
    insurance_carrier: str | None
    windows: list[tuple[datetime, datetime]] = field(default_factory=list)


def _clock(when: datetime) -> str:
    return f"{when.hour % 12 or 12}:{when:%M}"


def window_label(start: datetime, end: datetime) -> str:
    """Thu 8:00–12:00 — same day assumed, as the calendar windows are."""
    return f"{start:%a} {_clock(start)}–{_clock(end)}"


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def call_agent_prompt(spec: CallSpec) -> str:
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
