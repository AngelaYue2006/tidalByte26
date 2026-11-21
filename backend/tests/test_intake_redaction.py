"""T2: run the 20 fixture utterances through local_intake.redact; assert dropped fields and kept fields.

All 20 fixture utterances plus two inline cases run. Two stand-in models drive the pipeline without Ollama: PerfectModel answers with the fixture's expected values and
BlankModel answers with nothing useful, which exercises the regex backstop. Every output must validate against
shared/intake_request.schema.json and must not contain any value that was supposed to be dropped. Set
LIFELINE_LIVE_INTAKE=1 with OLLAMA_BASE_URL and NEMOTRON_NANO_TAG to run the same set through the real model.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from app import metrics
from app.nemotron import intake_backstop as backstop
from app.nemotron import local_intake
from app.nemotron.local_intake import IntakeError, OllamaClient, redact
from app.nemotron.types import IntakeRequest, UserRecord
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend" / "fixtures" / "intake_utterances.jsonl"
SCHEMA = json.loads((ROOT / "shared" / "intake_request.schema.json").read_text())
USERS = json.loads((ROOT / "backend" / "fixtures" / "users.json").read_text())

# Words that name symptoms, medications or mobility details in the fixture; none may survive into the output.
SENSITIVE_WORDS = (
    "ibuprofen", "metformin", "lisinopril", "vicodin", "warfarin", "toothache", "spasm", "mole", "dizzy",
    "pacemaker", "knee", "walker", "fall", "johnson", "mary", "sarah", "1948", "1945", "example street", "demo-", "555-",
)

INLINE_CASES = [
    {
        "id": "inline_demo",
        "now": "2026-11-23T09:00:00-06:00",
        "utterance": "I need a dental cleaning this week, under $150. I have Delta Dental. My knee makes walking hard so I'll need a ride.",
        "expected": {
            "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental",
            "time_range": {"start": "2026-11-23T00:00:00-06:00", "end": "2026-11-29T23:59:59-06:00"},
            "needs_ride": True, "search_area": "near home",
        },
        "expected_dropped": ["mobility_details"],
    },
    {
        "id": "inline_identifiers",
        "now": "2026-11-23T09:00:00-06:00",
        "utterance": "Mary Johnson, born 3/14/48, member DEMO-0000-0000-0001, 100 Example Street. Eye exam next week, Medicare, call 555-555-0101.",
        "expected": {
            "care_type": "eye exam", "budget_max": None, "insurance_carrier": "Medicare",
            "time_range": {"start": "2026-11-30T00:00:00-06:00", "end": "2026-12-06T23:59:59-06:00"},
            "needs_ride": False, "search_area": "near home",
        },
        "expected_dropped": ["member_id", "date_of_birth", "address", "contact_phone", "patient_name"],
    },
]


def fixture_rows() -> list[dict]:
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    assert len(rows) == 20, f"intake_utterances.jsonl must hold the 20 utterances from #4, found {len(rows)}"
    return rows


ROWS = fixture_rows() + INLINE_CASES
IDS = [r["id"] for r in ROWS]


def owner() -> UserRecord:
    if isinstance(USERS, dict) and "owner" in USERS:
        return UserRecord.model_validate(USERS["owner"])
    return UserRecord(id="mary", name="Mary Johnson", phone_e164="+15555550100", timezone="America/Chicago")


def phrase_for(expected: dict, now: datetime) -> str:
    want = (expected["time_range"]["start"], expected["time_range"]["end"])
    for phrase in backstop.TIME_PHRASES:
        if backstop.resolve_time_range(phrase, now) == want:
            return phrase
    raise AssertionError(f"no phrase resolves to {want}")


class PerfectModel:
    """What a flawless Nano would say."""

    name = "perfect-stub"

    def __init__(self, row: dict) -> None:
        self.row = row
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        self.calls.append(user)
        e = self.row["expected"]
        return {
            "care_type": e["care_type"], "budget_max": e["budget_max"], "insurance_carrier": e["insurance_carrier"],
            "time_phrase": phrase_for(e, datetime.fromisoformat(self.row["now"])), "needs_ride": e["needs_ride"],
            "search_area": e["search_area"], "dropped_fields": list(self.row["expected_dropped"]),
        }


class BlankModel:
    """Gets the care type and nothing else; the backstop has to do the rest."""

    name = "blank-stub"

    def __init__(self, row: dict) -> None:
        self.row = row

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        return {
            "care_type": self.row["expected"]["care_type"], "budget_max": None, "insurance_carrier": None,
            "time_phrase": "", "needs_ride": False, "search_area": None, "dropped_fields": [],
        }


class LeakyModel(PerfectModel):
    """Copies identifiers into fields it should not (the pre-review leak case; kept)."""

    name = "leaky-stub"

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        out = super().complete_json(system, user, schema)
        out["search_area"] = "100 Example Street, Chicago"
        out["insurance_carrier"] = "Delta Dental DEMO-0000-0000-0001"
        return out


@pytest.fixture(autouse=True)
def metrics_file(tmp_path, monkeypatch):
    """Tests write metrics to a scratch file. A live run (LIFELINE_LIVE_INTAKE=1) keeps METRICS_PATH so the
    redaction rows land in the real metrics.jsonl for scripts/metrics_summary.py."""
    if os.environ.get("LIFELINE_LIVE_INTAKE") == "1":
        return Path(os.environ.get("METRICS_PATH", "metrics.jsonl"))
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("METRICS_PATH", str(path))
    return path


def run(row: dict, model) -> IntakeRequest:
    return redact(row["utterance"], owner(), model=model, now=datetime.fromisoformat(row["now"]))


def assert_no_leak(row: dict, request: IntakeRequest) -> None:
    out = request.model_dump_json().lower()
    for value in backstop.identifier_values(row["utterance"]):
        assert value.lower() not in out, (row["id"], value)
    if row["expected_dropped"]:
        for word in SENSITIVE_WORDS:
            assert word not in out, (row["id"], word)
    assert row["utterance"].lower() not in out


def test_all_twenty_fixture_rows_plus_inline_cases_run():
    assert len(ROWS) == 20 + len(INLINE_CASES)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_perfect_model_output_matches_expected_and_schema(row):
    request = run(row, PerfectModel(row))
    Draft202012Validator(SCHEMA).validate(request.model_dump())
    assert request.model_dump(exclude={"dropped_fields"}) == row["expected"], row["id"]
    assert request.dropped_fields == sorted(row["expected_dropped"], key=backstop.DROPPABLE_ORDER)
    assert_no_leak(row, request)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_backstop_recovers_budget_carrier_time_and_identifiers(row):
    request = run(row, BlankModel(row))
    Draft202012Validator(SCHEMA).validate(request.model_dump())
    e = row["expected"]
    assert request.budget_max == e["budget_max"], row["id"]
    assert request.insurance_carrier == e["insurance_carrier"], row["id"]
    assert request.time_range.model_dump() == e["time_range"], row["id"]
    assert request.needs_ride == e["needs_ride"], row["id"]
    detectable = {"member_id", "contact_phone", "date_of_birth", "address"}
    assert set(request.dropped_fields) & detectable == set(row["expected_dropped"]) & detectable, row["id"]
    assert_no_leak(row, request)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_leaky_model_is_scrubbed(row):
    request = run(row, LeakyModel(row))
    assert request.search_area == "near home"
    assert request.insurance_carrier in (None, row["expected"]["insurance_carrier"])
    assert "address" in request.dropped_fields
    assert_no_leak(row, request)
    Draft202012Validator(SCHEMA).validate(request.model_dump())


def test_report_fields_kept_and_dropped(capsys, metrics_file):
    """The T2 report: per utterance, which fields were kept and which kinds were dropped. Each row is also scored into
    metrics.jsonl (kind `redaction`, model `perfect-stub`) so `scripts/metrics_summary.py` has the shape it reads."""
    lines = []
    for row in ROWS:
        model = PerfectModel(row)
        request = run(row, model)
        kept = [k for k, v in request.model_dump(exclude={"dropped_fields"}).items() if v not in (None, "")]
        lines.append(f"{row['id']}: kept {','.join(kept)}; dropped {','.join(request.dropped_fields) or '-'}")
        scored = metrics.record_redaction(model.name, row["id"], row["expected"], row["expected_dropped"], request.model_dump())
        assert scored["kept_correct"] == scored["kept_expected"] == 6 and scored["dropped_correct"] == scored["dropped_expected"], row["id"]
    print("\nT2 redaction report\n" + "\n".join(lines))
    assert len(lines) == len(ROWS)
    assert sum(1 for line in metrics_file.read_text().splitlines() if '"kind": "redaction"' in line) == len(ROWS)


def test_raw_text_is_never_logged_above_debug(caplog):
    row = ROWS[0]
    with caplog.at_level(logging.INFO, logger="app.nemotron.local_intake"):
        run(row, PerfectModel(row))
    assert caplog.records, "intake logs one INFO line"
    for record in caplog.records:
        assert row["utterance"] not in record.getMessage()
        assert record.levelno >= logging.INFO


def test_metrics_record_latency_without_text(metrics_file):
    row = ROWS[0]
    run(row, PerfectModel(row))
    rows = [json.loads(line) for line in metrics_file.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["kind"] == "intake"
    assert rows[0]["model"] == "perfect-stub"
    assert isinstance(rows[0]["latency_ms"], int) and rows[0]["latency_ms"] >= 0
    assert row["utterance"] not in metrics_file.read_text()
    with pytest.raises(ValueError):
        metrics.record("intake", text="never")


class FakeHttpClient:
    """Stands in for httpx.Client: records how it was built and what was posted."""

    built: ClassVar[list[dict]] = []
    posts: ClassVar[list[str]] = []

    def __init__(self, **kwargs) -> None:
        FakeHttpClient.built.append(kwargs)

    def post(self, path: str, json: dict | None = None):
        FakeHttpClient.posts.append(path)

        class Response:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {"message": {"content": __import__("json").dumps(PerfectModel(ROWS[0]).complete_json("", "", {}))}}

        return Response()


@pytest.fixture
def fake_http(monkeypatch):
    FakeHttpClient.built.clear()
    FakeHttpClient.posts.clear()
    monkeypatch.setattr(httpx, "Client", FakeHttpClient)
    return FakeHttpClient


def test_ollama_client_only_calls_ollama_base_url_and_ignores_proxies(fake_http):
    client = OllamaClient("http://localhost:11434/", "nano-test-tag")
    request = run(ROWS[0], client)
    assert request.care_type == ROWS[0]["expected"]["care_type"]
    assert fake_http.posts == ["/api/chat"]
    (built,) = fake_http.built
    assert built["base_url"] == "http://localhost:11434"
    assert built["trust_env"] is False, "HTTP(S)_PROXY from the environment must never route intake text"


@pytest.mark.parametrize(
    "url",
    ["http://ollama.example.com:11434", "http://10.0.0.5:11434", "https://api.example.com", "http://localhost.evil.com:11434",
     "ftp://localhost:11434", "localhost:11434"],
)
def test_remote_ollama_url_is_refused_before_any_request(url, fake_http):
    with pytest.raises(IntakeError, match="OLLAMA_BASE_URL must point at this machine"):
        OllamaClient(url, "nano-test-tag")
    assert fake_http.built == [] and fake_http.posts == []


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434", "https://ollama.localhost"])
def test_local_ollama_urls_are_accepted(url, fake_http):
    OllamaClient(url, "nano-test-tag")
    assert len(fake_http.built) == 1


class AdversarialModel(PerfectModel):
    """A Nano that lets sensitive content into the structured fields."""

    name = "adversarial-stub"

    def __init__(self, row: dict, **overrides) -> None:
        super().__init__(row)
        self.overrides = overrides

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        return super().complete_json(system, user, schema) | self.overrides


@pytest.mark.parametrize(
    ("care_type", "cleaned"),
    [("dental cleaning for a toothache", "dental cleaning"), ("dental cleaning, 3/14/48", "dental cleaning"),
     ("Dental Cleaning - Mary Johnson", "dental cleaning"), ("dental cleaning because my gums bleed", "dental cleaning"),
     ("Cardiology follow-up with Dr. Smith", "cardiology follow-up")],
)
def test_content_after_a_connective_is_cut_from_care_type(care_type, cleaned):
    row = ROWS[0]
    request = run(row, AdversarialModel(row, care_type=care_type))
    assert request.care_type == cleaned
    assert_no_leak(row, request)


@pytest.mark.parametrize(
    "care_type",
    ["toothache dentist", "metformin blood test", "lisinopril refill", "mary johnson cleaning", "Mary Johnson", "knee cleaning",
     "walker dental cleaning", "pacemaker checkup", "cleaning alex taylor", "dental cleaning sarah", "Dr. Patel cleaning",
     "cleaning at Bright Smile", "sleepy time nap"],
)
def test_care_type_outside_the_appointment_vocabulary_fails_closed(care_type):
    """A name (the owner's, a contact's, a stranger's), a symptom, a drug or an unknown word never leaves as care_type."""
    row = ROWS[0]
    with pytest.raises(IntakeError, match="INTAKE_INCOMPLETE"):
        run(row, AdversarialModel(row, care_type=care_type))


def test_search_area_leaves_only_as_a_place_the_speaker_named():
    """Known place and spoken: accepted in canonical form. Known place not spoken, or unknown: near home."""
    spoken = ROWS[0] | {"utterance": "Eye exam near Oak Park please, I have VSP."}
    spoken["expected"] = spoken["expected"] | {"insurance_carrier": "VSP", "budget_max": None, "needs_ride": False, "search_area": "Oak Park, IL"}
    assert run(spoken, AdversarialModel(spoken, search_area="oak park, IL")).search_area == "Oak Park, IL"
    assert run(spoken, AdversarialModel(spoken, search_area="Oak Park")).search_area == "Oak Park, IL"
    assert run(spoken, AdversarialModel(spoken, search_area="Evanston, IL")).search_area == "near home"
    for row in ROWS:
        if row["expected"]["search_area"] != "near home":
            assert backstop.verified_place(row["expected"]["search_area"], row["utterance"]) == row["expected"]["search_area"], row["id"]


def test_every_fixture_care_type_is_in_the_vocabulary():
    for row in ROWS:
        assert backstop.unsupported_care_terms(row["expected"]["care_type"]) == [], row["id"]


CONTACT_ON_BEHALF = {
    "id": "inline_contact_on_behalf",
    "now": "2026-11-23T09:00:00-06:00",
    "utterance": "This is Sarah Johnson calling for my mother. She needs a dental cleaning this week, under $150, with Delta Dental, and a ride.",
    "expected": {
        "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental",
        "time_range": {"start": "2026-11-23T00:00:00-06:00", "end": "2026-11-29T23:59:59-06:00"},
        "needs_ride": True, "search_area": "near home",
    },
    "expected_dropped": ["patient_name"],
}


def test_contact_name_absent_from_owner_record_never_leaves():
    """The speaker is the contact, not the owner, so her name is in no on-device record. It still may not leave."""
    row = CONTACT_ON_BEHALF
    clean = run(row, PerfectModel(row))
    assert clean.model_dump(exclude={"dropped_fields"}) == row["expected"]
    with pytest.raises(IntakeError, match="INTAKE_INCOMPLETE"):
        run(row, AdversarialModel(row, care_type="dental cleaning sarah"))
    with pytest.raises(IntakeError, match="INTAKE_INCOMPLETE"):
        run(row, AdversarialModel(row, care_type="Sarah Johnson"))
    area = run(row, AdversarialModel(row, search_area="near Sarah Johnson"))
    assert area.search_area == "near home" and "patient_name" in area.dropped_fields
    shaped = run(row, AdversarialModel(row, search_area="Sarah Johnson, IL"))
    assert shaped.search_area == "near home" and "patient_name" in shaped.dropped_fields
    carrier_row = row | {"utterance": row["utterance"].replace("with Delta Dental, ", "")}
    carrier_row["expected"] = carrier_row["expected"] | {"insurance_carrier": None}
    carrier = run(carrier_row, AdversarialModel(carrier_row, insurance_carrier="Sarah Johnson"))
    assert carrier.insurance_carrier is None
    assert "sarah" not in json.dumps([clean.model_dump(), area.model_dump(), carrier.model_dump()]).lower()


@pytest.mark.parametrize(
    ("field", "value", "safe"),
    [
        ("search_area", "near Mary Johnson", "near home"),
        ("search_area", "100 Example Street, Chicago", "near home"),
        ("search_area", "the clinic by my knee doctor", "near home"),
        ("search_area", "Evanston", "near home"),
        ("search_area", "Evanston, IL", "near home"),
        ("search_area", "near Alex Taylor", "near home"),
        ("search_area", "Alex Taylor, IL", "near home"),
        ("search_area", "Sarah Johnson, IL", "near home"),
        ("search_area", "Springfield, IL", "near home"),
        ("insurance_carrier", "Delta Dental DEMO-0000-0000-0001", None),
        ("insurance_carrier", "Medicare for her diabetes", "Medicare"),
        ("insurance_carrier", "Mary Johnson", None),
        ("insurance_carrier", "Alex Taylor", None),
        ("insurance_carrier", "delta", "Delta Dental"),
        ("insurance_carrier", "Some Unknown Plan", None),
    ],
)
def test_sensitive_carrier_or_area_falls_back_to_safe_value(field, value, safe):
    # No carrier in this utterance, so the model's insurance_carrier is what gets checked.
    row = ROWS[0] | {"utterance": "I need a dental cleaning this week, under $150, and I'll need a ride."}
    row["expected"] = row["expected"] | {"insurance_carrier": None}
    request = run(row, AdversarialModel(row, **{field: value}))
    assert getattr(request, field) == safe
    assert_no_leak(row, request)
    Draft202012Validator(SCHEMA).validate(request.model_dump())


def test_owner_record_values_never_leave_even_when_absent_from_the_utterance():
    row = ROWS[0]
    user = owner()
    out = run(row, AdversarialModel(row, search_area=f"near {user.home.address if user.home else '100 Example Street'}"))
    assert "address" in out.dropped_fields and out.search_area == "near home"
    with pytest.raises(IntakeError):
        run(row, AdversarialModel(row, care_type=f"cleaning {user.name.split()[0]}"))


def test_missing_model_tag_raises_instead_of_guessing(monkeypatch):
    monkeypatch.delenv("NEMOTRON_NANO_TAG", raising=False)
    with pytest.raises(IntakeError, match="NEMOTRON_NANO_TAG"):
        local_intake.from_env()


def test_empty_utterance_is_intake_incomplete():
    with pytest.raises(IntakeError, match="INTAKE_INCOMPLETE"):
        redact("   ", owner(), model=PerfectModel(ROWS[0]))


@pytest.mark.skipif(os.environ.get("LIFELINE_LIVE_INTAKE") != "1", reason="set LIFELINE_LIVE_INTAKE=1 with Ollama running")
def test_live_nano_on_the_fixture_set(capsys):
    """Runs the set through the real local model. Fails only on a leak; prints accuracy per field for the pitch."""
    client = local_intake.from_env()
    hits = {k: 0 for k in ("care_type", "budget_max", "insurance_carrier", "time_range", "needs_ride", "search_area", "dropped_fields")}
    for row in ROWS:
        request = run(row, client)
        assert_no_leak(row, request)
        got = request.model_dump()
        metrics.record_redaction(client.name, row["id"], row["expected"], row["expected_dropped"], got)  # for the pitch table
        for key in hits:
            if key == "dropped_fields":
                hits[key] += set(got[key]) == set(row["expected_dropped"])
            elif key == "care_type":
                hits[key] += re.sub(r"\W", "", got[key]) == re.sub(r"\W", "", row["expected"][key])
            else:
                hits[key] += got[key] == row["expected"][key]
    print("\nLive Nano accuracy over", len(ROWS), "utterances:", {k: f"{v}/{len(ROWS)}" for k, v in hits.items()})
    print("Then: python scripts/metrics_summary.py", os.environ.get("METRICS_PATH", "metrics.jsonl"))
