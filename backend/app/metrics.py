"""Nemotron track metrics: redaction accuracy, intake latency, call-agent first-token latency, ranking latency. Writes to metrics.jsonl."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

# Keys that would carry a person's words. Metrics hold numbers and field names only.
_FORBIDDEN_KEYS = {"text", "utterance", "transcript", "raw", "message"}


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
