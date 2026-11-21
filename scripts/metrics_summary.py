#!/usr/bin/env python3
"""Print Nemotron / demo metrics for docs/PITCH.md and the Devpost.

Reads backend/metrics.jsonl when present (written by app/metrics.py, issue #25).
Falls back to docs/pitch_metrics.jsonl so the pitch always has a refreshable table.

Usage:
  python scripts/metrics_summary.py
  python scripts/metrics_summary.py path/to/metrics.jsonl
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = [
    ROOT / "backend" / "metrics.jsonl",
    ROOT / "docs" / "pitch_metrics.jsonl",
]

ORDER = [
    "redaction_kept",
    "redaction_dropped",
    "intake_latency_p50_ms",
    "intake_latency_p95_ms",
    "call_agent_first_token_p50_ms",
    "ranking_latency_p50_ms",
    "bytes_to_cloud_per_request",
    "time_to_booked_lifeline_s",
    "time_to_booked_manual_s",
]

LABELS = {
    "redaction_kept": "Redaction kept (fraction of expected fields)",
    "redaction_dropped": "Redaction dropped (fraction of expected drops)",
    "intake_latency_p50_ms": "Intake latency p50 (ms)",
    "intake_latency_p95_ms": "Intake latency p95 (ms)",
    "call_agent_first_token_p50_ms": "Call-agent first token p50 (ms)",
    "ranking_latency_p50_ms": "Ranking latency p50 (ms)",
    "bytes_to_cloud_per_request": "Bytes sent to cloud per request",
    "time_to_booked_lifeline_s": "Time to booked — LifeLine (s)",
    "time_to_booked_manual_s": "Time to booked — manual (s)",
}


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def summarize_raw(rows: list[dict]) -> dict[str, float | None]:
    """Aggregate event-style metrics.jsonl from app/metrics.py when that lands."""
    by_name: dict[str, list[float]] = defaultdict(list)
    out: dict[str, float | None] = {k: None for k in ORDER}

    for row in rows:
        if "metric" in row and "value" in row:
            name = row["metric"]
            if name in out:
                out[name] = row["value"]
            continue
        # Event shape: {"type": "intake_latency", "ms": 1234, ...}
        kind = row.get("type") or row.get("name")
        if kind == "intake_latency" and "ms" in row:
            by_name["intake"].append(float(row["ms"]))
        elif kind in {"call_agent_first_token", "first_token"} and "ms" in row:
            by_name["first_token"].append(float(row["ms"]))
        elif kind in {"ranking_latency", "rank"} and "ms" in row:
            by_name["rank"].append(float(row["ms"]))
        elif kind == "redaction" and "kept" in row and "dropped" in row:
            by_name["kept"].append(float(row["kept"]))
            by_name["dropped"].append(float(row["dropped"]))
        elif kind == "bytes_to_cloud" and "bytes" in row:
            by_name["bytes"].append(float(row["bytes"]))

    def p50(xs: list[float]) -> float | None:
        return statistics.median(xs) if xs else None

    def p95(xs: list[float]) -> float | None:
        if not xs:
            return None
        xs = sorted(xs)
        idx = min(len(xs) - 1, max(0, int(round(0.95 * (len(xs) - 1)))))
        return xs[idx]

    if by_name["intake"]:
        out["intake_latency_p50_ms"] = p50(by_name["intake"])
        out["intake_latency_p95_ms"] = p95(by_name["intake"])
    if by_name["first_token"]:
        out["call_agent_first_token_p50_ms"] = p50(by_name["first_token"])
    if by_name["rank"]:
        out["ranking_latency_p50_ms"] = p50(by_name["rank"])
    if by_name["kept"]:
        out["redaction_kept"] = p50(by_name["kept"])
    if by_name["dropped"]:
        out["redaction_dropped"] = p50(by_name["dropped"])
    if by_name["bytes"]:
        out["bytes_to_cloud_per_request"] = p50(by_name["bytes"])
    return out


def fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value != int(value) and abs(value) < 10:
        return f"{value:.2f}"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULTS
    merged: dict[str, float | None] = {k: None for k in ORDER}
    used: list[str] = []
    notes: list[str] = []

    for path in paths:
        rows = load_rows(path)
        if not rows:
            continue
        used.append(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
        part = summarize_raw(rows)
        for k, v in part.items():
            if v is not None:
                merged[k] = v
        for row in rows:
            if row.get("metric") in {"time_to_booked_lifeline_s", "time_to_booked_manual_s"}:
                if row.get("note"):
                    notes.append(f"- {row['metric']}: {row['note']}")

    print("# LifeLine metrics summary")
    print(f"Sources: {', '.join(used) if used else '(none found)'}")
    print()
    print("| Metric | Value |")
    print("|---|---|")
    for key in ORDER:
        print(f"| {LABELS[key]} | {fmt(merged.get(key))} |")

    life = merged.get("time_to_booked_lifeline_s")
    manual = merged.get("time_to_booked_manual_s")
    if life and manual and life > 0:
        print()
        print(
            f"**Time-to-booked comparison:** LifeLine {fmt(life)} s vs manual {fmt(manual)} s "
            f"({manual / life:.1f}× faster on this measurement)."
        )
    if notes:
        print()
        print("Notes:")
        for n in notes:
            print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
