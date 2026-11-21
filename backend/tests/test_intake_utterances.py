"""Shape of the 20-utterance redaction set (issue #4), the input to T2 and app/metrics.py.

Vocabulary follows shared/intake_request.schema.json: `expected` holds the six IntakeRequest fields minus
`dropped_fields`, which is `expected_dropped`. `budget_max` is whole dollars or null; `time_range` is `{start, end}`
in America/Chicago resolved from the phrase in the utterance as of `now` (Monday 2026-11-23 09:00, the demo week);
`search_area` is "near home" or "<place>, IL". `expected_dropped` names removed fields, never values.
"""

import json
import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "intake_utterances.jsonl"
INTAKE_FIELDS = {"care_type", "budget_max", "insurance_carrier", "time_range", "needs_ride", "search_area"}
DROPPABLE = {"symptoms", "medications", "member_id", "date_of_birth", "address", "contact_phone", "patient_name", "mobility_details"}
NOW = "2026-11-23T09:00:00-06:00"
ISO_CST = r"^2026-(11|12)-\d{2}T\d{2}:\d{2}:\d{2}-06:00$"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_twenty_well_formed_lines(rows: list[dict]) -> None:
    assert len(rows) == 20
    assert len({r["id"] for r in rows}) == 20
    for r in rows:
        assert set(r) == {"id", "now", "utterance", "expected", "expected_dropped"}, r["id"]
        assert r["now"] == NOW
        assert r["utterance"].strip()
        assert set(r["expected"]) == INTAKE_FIELDS, r["id"]
        e = r["expected"]
        assert isinstance(e["care_type"], str) and e["care_type"]
        assert e["budget_max"] is None or (isinstance(e["budget_max"], int) and e["budget_max"] > 0)
        assert e["insurance_carrier"] is None or e["insurance_carrier"].strip()
        tr = e["time_range"]
        assert set(tr) == {"start", "end"} and tr["start"] < tr["end"], (r["id"], tr)
        assert re.match(ISO_CST, tr["start"]) and re.match(ISO_CST, tr["end"]), r["id"]
        assert tr["start"] >= NOW[:10], (r["id"], "range starts before the request")
        assert isinstance(e["needs_ride"], bool)
        assert e["search_area"] == "near home" or e["search_area"].endswith(", IL")


def test_dropped_fields_are_names_never_values(rows: list[dict]) -> None:
    with_drops = [r for r in rows if r["expected_dropped"]]
    assert len(with_drops) >= 12
    for r in rows:
        assert len(set(r["expected_dropped"])) == len(r["expected_dropped"]), r["id"]
        assert set(r["expected_dropped"]) <= DROPPABLE, (r["id"], r["expected_dropped"])
    covered = {d for r in rows for d in r["expected_dropped"]}
    assert {"symptoms", "medications", "member_id", "date_of_birth", "address", "contact_phone"} <= covered


def test_dropped_values_never_survive_into_expected(rows: list[dict]) -> None:
    kept = json.dumps([r["expected"] for r in rows]).lower()
    for leak in ("demo-0000", "555-", "example street", "1948", "1945", "ibuprofen", "metformin", "warfarin", "johnson"):
        assert leak not in kept, leak


def test_mix_of_care_types_budgets_carriers_times_and_rides(rows: list[dict]) -> None:
    expected = [r["expected"] for r in rows]
    assert len({e["care_type"] for e in expected}) >= 8
    assert len({e["insurance_carrier"] for e in expected if e["insurance_carrier"]}) >= 5
    assert any(e["insurance_carrier"] is None for e in expected)
    assert len({(e["time_range"]["start"], e["time_range"]["end"]) for e in expected}) >= 5
    assert sum(e["needs_ride"] for e in expected) >= 6
    assert sum(not e["needs_ride"] for e in expected) >= 6
    assert any(e["budget_max"] is None for e in expected)
    with_budget = [r for r in rows if r["expected"]["budget_max"] is not None]
    assert any("$" in r["utterance"] for r in with_budget), "a budget as a number"
    assert any("$" not in r["utterance"] and not any(ch.isdigit() for ch in r["utterance"].split("under")[-1][:40])
               for r in with_budget if "under" in r["utterance"]), "a budget as words"
