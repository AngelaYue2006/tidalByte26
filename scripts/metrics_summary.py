#!/usr/bin/env python3
"""Print the Nemotron metrics table for docs/PITCH.md and the Devpost from metrics.jsonl.

    python scripts/metrics_summary.py [metrics.jsonl] [--json]

Reads the rows backend/app/metrics.py writes (kinds intake, redaction, ranking, call_agent). One table per model,
so numbers from a test stub ("perfect-stub") are never mistaken for the live Nano, Lightning or Super. Rows that
no run has produced yet print as "—". Standard library only; no backend import, so it runs anywhere.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

PENDING = "—"

# Table rows as docs/PITCH.md lists them: label, kind, field, statistic.
ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Redaction kept (fraction of expected fields)", "redaction", "kept", "fraction"),
    ("Redaction dropped (fraction of expected drops)", "redaction", "dropped", "fraction"),
    ("Intake latency p50 (ms)", "intake", "latency_ms", "p50"),
    ("Intake latency p95 (ms)", "intake", "latency_ms", "p95"),
    ("Call-agent first token p50 (ms)", "call_agent", "first_token_ms", "p50"),
    ("Ranking latency p50 (ms)", "ranking", "latency_ms", "p50"),
    ("Bytes sent to cloud per request", "intake", "cloud_bytes", "mean"),
)


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; p50 of [1,2,3,4] is 2, p95 of 20 values is the 19th."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def statistic(rows: list[dict], field: str, stat: str) -> str:
    if stat == "fraction":
        correct = sum(int(r.get(f"{field}_correct", 0)) for r in rows)
        expected = sum(int(r.get(f"{field}_expected", 0)) for r in rows)
        return PENDING if not expected else f"{correct}/{expected} = {correct / expected:.0%}"
    values = [float(r[field]) for r in rows if isinstance(r.get(field), int | float)]
    if not values:
        return PENDING
    if stat == "mean":
        return f"{sum(values) / len(values):.0f} (max {max(values):.0f})"
    return f"{percentile(values, 50 if stat == 'p50' else 95):.0f}"


def summarise(rows: list[dict]) -> dict[str, dict[str, str]]:
    """{model: {row label: value}} for every model seen, plus the sample counts per kind."""
    by_model: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_model[str(row.get("model", "unknown"))][str(row.get("kind"))].append(row)
    out: dict[str, dict[str, str]] = {}
    for model, kinds in sorted(by_model.items()):
        table = {label: statistic(kinds.get(kind, []), field, stat) for label, kind, field, stat in ROWS}
        table["Samples"] = ", ".join(f"{kind} n={len(kinds[kind])}" for kind in sorted(kinds))
        out[model] = table
    return out


def render(summary: dict[str, dict[str, str]], path: Path) -> str:
    if not summary:
        return f"No metrics in {path}. Run the T2 test or the pipeline with METRICS_PATH={path} first."
    lines = [f"Nemotron metrics from `{path}` ({sum(1 for _ in load_rows(path))} rows). Stub models are test doubles, not Nemotron."]
    for model, table in summary.items():
        lines += ["", f"### model `{model}`", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| {label} | {value} |" for label, value in table.items()]
    lines += ["", f"Time to booked (GranniAI vs manual): {PENDING}, measured by hand on a timed full run, not by this script."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else Path(os.environ.get("METRICS_PATH", "metrics.jsonl"))
    summary = summarise(load_rows(path))
    print(json.dumps(summary, indent=2, ensure_ascii=False) if "--json" in argv else render(summary, path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
