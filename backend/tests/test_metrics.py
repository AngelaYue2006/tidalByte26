"""Issue #25: metrics rows carry numbers and names only, redaction scoring is exact, and the summary script prints the pitch table per model."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from app import metrics

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "scripts" / "metrics_summary.py"

EXPECTED = {
    "care_type": "cardiology follow-up", "budget_max": None, "insurance_carrier": "Humana",
    "time_range": {"start": "2026-11-30T00:00:00-06:00", "end": "2026-12-06T23:59:59-06:00"},
    "needs_ride": True, "search_area": "near home",
}
EXPECTED_DROPPED = ["date_of_birth", "symptoms", "mobility_details"]


def load_summary():
    spec = importlib.util.spec_from_file_location("metrics_summary", SUMMARY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def metrics_file(tmp_path, monkeypatch):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("METRICS_PATH", str(path))
    return path


def test_record_refuses_text_and_writes_one_json_line(metrics_file):
    row = metrics.record("intake", model="m", latency_ms=12)
    lines = metrics_file.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["latency_ms"] == 12 and row["kind"] == "intake"
    for key in ("text", "utterance", "transcript", "raw", "message"):
        with pytest.raises(ValueError, match="text fields"):
            metrics.record("intake", **{key: "never"})


def test_redaction_scores_exact_match_and_partial():
    perfect = {**EXPECTED, "dropped_fields": list(EXPECTED_DROPPED)}
    assert metrics.redaction_scores(EXPECTED, EXPECTED_DROPPED, perfect) == {
        "kept_expected": 6, "kept_correct": 6, "dropped_expected": 3, "dropped_correct": 3, "dropped_extra": 0,
    }
    partial = {**EXPECTED, "care_type": "cardiology followup", "insurance_carrier": None, "dropped_fields": ["symptoms", "address"]}
    assert metrics.redaction_scores(EXPECTED, EXPECTED_DROPPED, partial) == {
        "kept_expected": 6, "kept_correct": 5, "dropped_expected": 3, "dropped_correct": 1, "dropped_extra": 1,
    }


def test_record_redaction_and_helpers_write_names_and_numbers_only(metrics_file):
    metrics.record_redaction("nano-test", "u18", EXPECTED, EXPECTED_DROPPED, {**EXPECTED, "dropped_fields": EXPECTED_DROPPED})
    metrics.record_ranking("super-test", 812, 3)
    metrics.record_first_token("lightning-test", "call-a", 640)
    rows = [json.loads(line) for line in metrics_file.read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["redaction", "ranking", "call_agent"]
    assert rows[0]["utterance_id"] == "u18" and rows[0]["kept_correct"] == 6
    assert rows[1] == {**rows[1], "model": "super-test", "latency_ms": 812, "offers": 3}
    assert rows[2]["first_token_ms"] == 640
    text = metrics_file.read_text()
    assert "Humana" not in text and "cardiology" not in text, "values never reach the metrics file"


def test_percentile_is_nearest_rank():
    summary = load_summary()
    assert summary.percentile([1, 2, 3, 4], 50) == 2
    assert summary.percentile([4, 3, 2, 1], 95) == 4
    assert summary.percentile(list(range(1, 21)), 95) == 19
    assert summary.percentile([7], 50) == 7


def test_summary_groups_by_model_and_marks_missing_rows_pending(metrics_file):
    for i in range(20):
        metrics.record("intake", model="nano:4bit", model_ms=100 + i, latency_ms=100 + i * 10, utterance_chars=80, cloud_bytes=210 + i, kept=[], dropped=[])
        metrics.record_redaction("nano:4bit", f"u{i:02d}", EXPECTED, EXPECTED_DROPPED, {**EXPECTED, "dropped_fields": EXPECTED_DROPPED[: 2 + (i % 2)]})
    metrics.record_ranking("nvidia/super", 700, 3)
    metrics.record_ranking("nvidia/super", 900, 2)
    metrics.record("intake", model="perfect-stub", latency_ms=1, cloud_bytes=200)
    summary = load_summary()
    table = summary.summarise(summary.load_rows(metrics_file))
    assert set(table) == {"nano:4bit", "nvidia/super", "perfect-stub"}
    nano = table["nano:4bit"]
    assert nano["Redaction kept (fraction of expected fields)"] == "120/120 = 100%"
    assert nano["Redaction dropped (fraction of expected drops)"] == "50/60 = 83%"
    assert nano["Intake latency p50 (ms)"] == "190" and nano["Intake latency p95 (ms)"] == "280"
    assert nano["Bytes sent to cloud per request"] == "220 (max 229)"
    assert nano["Call-agent first token p50 (ms)"] == summary.PENDING and nano["Ranking latency p50 (ms)"] == summary.PENDING
    assert table["nvidia/super"]["Ranking latency p50 (ms)"] == "700"
    assert table["perfect-stub"]["Redaction kept (fraction of expected fields)"] == summary.PENDING
    rendered = summary.render(table, metrics_file)
    assert "### model `nano:4bit`" in rendered and "Stub models are test doubles" in rendered
    assert "| Intake latency p95 (ms) | 280 |" in rendered


def test_summary_with_no_file_says_so(tmp_path):
    summary = load_summary()
    missing = tmp_path / "none.jsonl"
    assert summary.summarise(summary.load_rows(missing)) == {}
    assert "No metrics in" in summary.render({}, missing)
