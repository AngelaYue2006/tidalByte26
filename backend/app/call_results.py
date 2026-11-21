"""Turn one finished call into a structured result: parse the ElevenLabs data-collection fields, fill gaps with
Super, compute slotOk against the free windows, store calls.result_json, emit call_result and call_status.

Status comes from these structured fields and receipts, never from transcript text (invariant 4).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, update

from app.db import session_scope
from app.events import EventBus
from app.models import Call, Event, Task
from app.nemotron.call_summary import CallSummary, SummaryError, summarize_call
from app.nemotron.ranker import ChatJSON
from app.ranking import money, slot_label

log = logging.getLogger("lifeline.call_results")

WEEKDAYS = {name: i for i, names in enumerate([("mon", "monday"), ("tue", "tues", "tuesday"), ("wed", "weds", "wednesday"),
                                               ("thu", "thur", "thurs", "thursday"), ("fri", "friday"), ("sat", "saturday"), ("sun", "sunday")])
            for name in names}
_TIME = re.compile(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?!\d)", re.IGNORECASE)
# One unambiguous quote only: "$95", "95", "95.50 dollars", "USD 120". A range, several numbers or prose is missing.
_PRICE = re.compile(r"^(?:usd\s*|\$\s*)?(\d{1,5}(?:\.\d{1,2})?)\s*(?:usd|dollars?|bucks)?\.?$", re.IGNORECASE)
_YES = {"yes", "true", "y", "accepted", "accepts", "in network", "in-network", "covered", "takes it"}
_NO = {"no", "false", "n", "not accepted", "out of network", "out-of-network", "declined", "does not", "doesn't"}
SLOT_MINUTES = 60


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def collected_value(raw: object) -> str | None:
    """ElevenLabs data_collection_results entries are either plain values or {"value": ..., "rationale": ...}."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def parse_price(text: str | None) -> float | None:
    """A single quoted amount, or None. "between $95 and $175" is not a price; Super reads the transcript instead."""
    if not text:
        return None
    m = _PRICE.match(text.strip().replace(",", ""))
    return float(m.group(1)) if m else None


def parse_insured(text: str | None) -> bool | None:
    if not text:
        return None
    low = text.strip().lower().rstrip(".")
    if low in _YES or low.startswith("yes"):
        return True
    if low in _NO or low.startswith("no"):
        return False
    return None


def parse_slot(text: str | None, *, call_date: datetime, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    """'Thu 9:30', 'Friday at 4 pm', 'next Monday 10:00' -> the first such weekday on or after the call day, in the owner's tz;
    a same-day time only when it is still ahead. Without am/pm, 1-6 is afternoon and 7-12 is morning (12 is noon),
    which is how receptionists say clinic hours."""
    if not text:
        return None
    low = text.lower()
    day = next((idx for word, idx in WEEKDAYS.items() if re.search(rf"\b{word}\b", low)), None)
    tm = _TIME.search(low)
    if day is None or tm is None:
        return None
    hour, minute, ampm = int(tm.group(1)), int(tm.group(2) or 0), (tm.group(3) or "").replace(".", "")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and 1 <= hour <= 6:
        hour += 12
    now_local = call_date.astimezone(tz)
    today = now_local.date()
    ahead = (day - today.weekday()) % 7
    if "next" in low:
        ahead = ahead + 7 if ahead < 7 else ahead
    elif ahead == 0:
        # Same weekday as the call: keep it only when the time is still ahead today. A time already past is
        # ambiguous (today, or in a week?) and counts as missing, so Super reads the transcript instead.
        candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            return None
    start = datetime.combine(today + timedelta(days=ahead), datetime.min.time(), tzinfo=tz).replace(hour=hour, minute=minute)
    return start, start + timedelta(minutes=SLOT_MINUTES)


def windows_from_json(blob: str | None) -> list[Window]:
    return [Window(datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"])) for w in json.loads(blob or "[]")]


def slot_ok(start: datetime | None, end: datetime | None, windows: list[Window]) -> bool:
    return start is not None and end is not None and any(w.start <= start and end <= w.end for w in windows)


@dataclass(frozen=True)
class CallFacts:
    price_usd: float | None
    insured: bool | None
    slot_start: datetime | None
    slot_end: datetime | None
    slot_label: str | None
    source: str  # data_collection | super | mixed | incomplete

    @property
    def complete(self) -> bool:
        return self.price_usd is not None and self.insured is not None and self.slot_start is not None


def facts_from_collection(results: dict, *, call_date: datetime, tz: ZoneInfo) -> CallFacts:
    price = parse_price(collected_value(results.get("price")))
    insured = parse_insured(collected_value(results.get("insured")))
    slot = parse_slot(collected_value(results.get("slot")), call_date=call_date, tz=tz)
    start, end = slot if slot else (None, None)
    # The label is derived from the validated slot only; raw collected text never reaches a card or a contact.
    return CallFacts(price, insured, start, end, slot_label(start) if start else None, "data_collection")


def merge(facts: CallFacts, summary: CallSummary) -> CallFacts:
    """Data collection wins where it had a value; Super fills only the gaps."""
    start = facts.slot_start if facts.slot_start is not None else summary.slot_start
    end = facts.slot_end if facts.slot_start is not None else summary.slot_end
    return CallFacts(
        facts.price_usd if facts.price_usd is not None else summary.price_usd,
        facts.insured if facts.insured is not None else summary.insured,
        start,
        end,
        slot_label(start) if start else None,  # Super's free-text label is never shown; only a validated slot is
        "super" if not any((facts.price_usd is not None, facts.insured is not None, facts.slot_start is not None)) else "mixed",
    )


def result_json(facts: CallFacts, windows: list[Window]) -> dict:
    """What calls.result_json holds: the four card fields the task schema allows plus the structured facts for ranking."""
    ok = slot_ok(facts.slot_start, facts.slot_end, windows)
    return {
        "price": money(facts.price_usd) if facts.price_usd is not None else "",
        "slot": facts.slot_label or "",
        "insured": bool(facts.insured),
        "slotOk": ok,
        "price_usd": facts.price_usd,
        "slot_start": facts.slot_start.isoformat() if facts.slot_start else None,
        "slot_end": facts.slot_end.isoformat() if facts.slot_end else None,
        "source": facts.source if facts.complete else "incomplete",
    }


def _finalize(engine: Engine, bus: EventBus, call: Call, task: Task, stored: dict, events: list[tuple[str, dict]]) -> bool:
    """Claim the call and write its terminal state and event rows in ONE transaction, then publish.

    The claim is a conditional UPDATE (status != done); only the delivery whose UPDATE hits a row writes the events, so
    two concurrent deliveries cannot both emit, and a failure before commit leaves nothing for a retry to repair."""
    with session_scope(engine) as session:
        claimed = session.exec(
            update(Call)
            .where(Call.id == call.id, Call.status != "done")
            .values(status="done", result_json=json.dumps(stored), ended_at=datetime.now(UTC))
        ).rowcount
        if claimed != 1:
            return False
        rows = [Event(task_id=task.id, type=kind, payload_json=json.dumps(payload, ensure_ascii=False), visibility="contact") for kind, payload in events]
        session.add_all(rows)
        session.flush()
        for row in rows:
            session.refresh(row)
            session.expunge(row)
    for row in rows:
        bus.publish(row, task.owner_id)
    return True


def record_call_result(
    engine: Engine,
    bus: EventBus,
    call: Call,
    task: Task,
    collection: dict,
    transcript: list[dict],
    *,
    call_date: datetime,
    timezone: str,
    super_client: ChatJSON | None,
) -> dict:
    """Store the structured result and emit call_result (only when complete) and call_status done, atomically and once per call."""
    if call.status == "done":
        return {"duplicate": True}
    tz = ZoneInfo(timezone)
    facts = facts_from_collection(collection, call_date=call_date, tz=tz)
    if not facts.complete and transcript:
        if super_client is None:
            log.warning("call %s: data collection incomplete and no Super client; result stays incomplete", call.id)
        else:
            try:
                facts = merge(facts, summarize_call(transcript, client=super_client, call_date=call_date, timezone=timezone))
            except SummaryError as exc:
                log.warning("call %s: %s", call.id, exc)
    windows = windows_from_json(task.windows_json)
    stored = result_json(facts, windows)
    events: list[tuple[str, dict]] = []
    if facts.complete:
        events.append(("call_result", {"call_id": call.id, "price": stored["price"], "slot": stored["slot"], "insured": stored["insured"], "slotOk": stored["slotOk"]}))
    else:
        log.warning("call %s ended without a complete offer (source=%s); no call_result emitted", call.id, stored["source"])
    events.append(("call_status", {"call_id": call.id, "status": "done"}))
    if not _finalize(engine, bus, call, task, stored, events):
        return {"duplicate": True}
    return {"duplicate": False, "complete": facts.complete, "source": stored["source"]}


def record_call_failure(engine: Engine, bus: EventBus, call: Call, task: Task, reason: str) -> dict:
    """call_initiation_failure: the clinic was busy, did not answer, or the call never connected. Same atomic claim."""
    if call.status == "done":
        return {"duplicate": True}
    stored = {"error": "CALL_FAILED", "reason": reason}
    event = ("call_status", {"call_id": call.id, "status": "done", "error": "CALL_FAILED", "reason": reason})
    if not _finalize(engine, bus, call, task, stored, [event]):
        return {"duplicate": True}
    return {"duplicate": False, "error": "CALL_FAILED", "reason": reason}
