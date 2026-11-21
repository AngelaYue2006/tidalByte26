"""Nemotron track metrics: redaction accuracy, intake latency, call-agent first-token latency, ranking latency. Writes to metrics.jsonl.

One JSON line per observation, never a person's words. `scripts/metrics_summary.py` turns the file into the pitch table.

Row kinds and their fields (the contract the summary reads):
- `intake`:     model, model_ms, latency_ms, utterance_chars, cloud_bytes, kept[], dropped[]        (local_intake.redact)
- `redaction`:  model, utterance_id, kept_expected, kept_correct, dropped_expected, dropped_correct, dropped_extra  (T2)
- `ranking`:    model, latency_ms, offers                                                            (ranker.timed_rank)
- `call_agent`: model, call_id, first_token_ms                                                       (llm_proxy, #20)
- `contact_message`: model, latency_ms, chars, source (nano | template), violations[]                  (local_intake.contact_message)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

# Keys that would carry a person's words. Metrics hold numbers and field names only.
_FORBIDDEN_KEYS = {"text", "utterance", "transcript", "raw", "message"}

INTAKE_FIELDS: tuple[str, ...] = ("care_type", "budget_max", "insurance_carrier", "time_range", "needs_ride", "search_area")


def metrics_path() -> Path:
    return Path(os.environ.get("METRICS_PATH", "metrics.jsonl"))


def record(kind: str, **fields: object) -> dict:
    """Append one JSON line. Never pass text; pass lengths, latencies and field names."""
    leaked = _FORBIDDEN_KEYS & set(fields)
    if leaked:
        raise ValueError(f"metrics must not carry text fields: {sorted(leaked)}")
    row = {"kind": kind, "at": datetime.now(UTC).isoformat(timespec="milliseconds"), **fields}
    with metrics_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def redaction_scores(expected: dict, expected_dropped: list[str], got: dict) -> dict:
    """Compare one redacted request with the fixture's expectation. Counts only; no values leave this function.

    kept_expected / kept_correct: the six IntakeRequest fields, counted as correct when they match exactly
    (the model may say "cardiology follow-up" or "cardiology followup"; punctuation is ignored for care_type).
    dropped_expected / dropped_correct / dropped_extra: the field *names* in dropped_fields.
    """
    kept_correct = 0
    for field in INTAKE_FIELDS:
        want, have = expected.get(field), got.get(field)
        if field == "care_type" and isinstance(want, str) and isinstance(have, str):
            want, have = _squash(want), _squash(have)
        kept_correct += want == have
    want_dropped, have_dropped = set(expected_dropped), set(got.get("dropped_fields") or [])
    return {
        "kept_expected": len(INTAKE_FIELDS),
        "kept_correct": kept_correct,
        "dropped_expected": len(want_dropped),
        "dropped_correct": len(want_dropped & have_dropped),
        "dropped_extra": len(have_dropped - want_dropped),
    }


def record_redaction(model: str, utterance_id: str, expected: dict, expected_dropped: list[str], got: dict) -> dict:
    return record("redaction", model=model, utterance_id=utterance_id, **redaction_scores(expected, expected_dropped, got))


def record_ranking(model: str, latency_ms: int, offers: int) -> dict:
    return record("ranking", model=model, latency_ms=latency_ms, offers=offers)


def record_first_token(model: str, call_id: str, first_token_ms: int) -> dict:
    """Call-agent first-token latency, one row per proxy turn. Called by routers/llm_proxy.py."""
    return record("call_agent", model=model, call_id=call_id, first_token_ms=first_token_ms)


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())
