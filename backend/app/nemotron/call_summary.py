"""Nemotron Super as the transcript fallback: summarize_call(transcript, ...) -> CallSummary when the ElevenLabs data collection is missing a field.

Lives beside ranker.py (which #25 holds open) and reuses its client protocol and strict JSON parse. Same
rule as ranking: one strict parse, one retry with the problem named, then an error, never a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.nemotron.prompts import CALL_SUMMARY_SYSTEM, call_summary_user
from app.nemotron.rank_prompt import retry_user_message
from app.nemotron.ranker import BadReply, ChatJSON, parse_json_object


class SummaryError(Exception):
    """Super gave no usable summary after one retry."""


@dataclass(frozen=True)
class CallSummary:
    price_usd: float | None
    insured: bool | None
    slot_start: datetime | None
    slot_end: datetime | None
    slot_label: str | None


def _parse_dt(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadReply(f"{field} must be an ISO 8601 string or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BadReply(f"{field} is not ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BadReply(f"{field} must carry a timezone offset")
    return parsed


def _check(data: dict) -> CallSummary:
    for key in ("price_usd", "insured", "slot_start", "slot_end", "slot_label"):
        if key not in data:
            raise BadReply(f"missing key {key!r}")
    price = data["price_usd"]
    if price is not None and (isinstance(price, bool) or not isinstance(price, int | float) or not math.isfinite(price) or price < 0):
        raise BadReply("price_usd must be a non-negative number or null")
    insured = data["insured"]
    if insured is not None and not isinstance(insured, bool):
        raise BadReply("insured must be true, false or null")
    start, end = _parse_dt(data["slot_start"], "slot_start"), _parse_dt(data["slot_end"], "slot_end")
    if (start is None) != (end is None):
        raise BadReply("slot_start and slot_end must both be set or both be null")
    if start is not None and end <= start:
        raise BadReply("slot_end must be after slot_start")
    label = data["slot_label"]
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise BadReply("slot_label must be a short string or null")
    return CallSummary(float(price) if price is not None else None, insured, start, end, label.strip() if label else None)


def summarize_call(transcript: list[dict], *, client: ChatJSON, call_date: datetime, timezone: str) -> CallSummary:
    """Extract price, insurance and slot from the transcript lines. Raises SummaryError after one failed retry."""
    system = CALL_SUMMARY_SYSTEM
    user = call_summary_user(transcript, call_date_iso=call_date.isoformat(), timezone=timezone)
    previous: list[dict] = []
    for attempt in range(2):
        reply = client.complete_json(system, user, previous=previous or None)
        try:
            return _check(parse_json_object(reply))
        except BadReply as exc:
            if attempt == 1:
                raise SummaryError(f"Super gave no usable call summary after one retry: {exc}") from exc
            previous = [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            user = retry_user_message(reply, str(exc))
    raise SummaryError("unreachable")
