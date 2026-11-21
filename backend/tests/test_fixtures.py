"""Fixture facts the demo depends on (issue #3): synthetic people, three clinics, free windows, receptionist scripts."""

import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FAKE_PHONE = re.compile(r"^\+1555555(01\d\d)$")


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def users() -> dict:
    return load("users.json")


@pytest.fixture(scope="module")
def clinics() -> list[dict]:
    return load("clinics.json")["clinics"]


@pytest.fixture(scope="module")
def windows() -> dict:
    return load("free_windows.json")


@pytest.fixture(scope="module")
def receptionists() -> list[dict]:
    return load("receptionists.json")["receptionists"]


def test_owner_and_contact(users: dict) -> None:
    owner = users["owner"]
    assert owner["name"] == "Mary Johnson"
    assert owner["role"] == "owner"
    assert owner["insurance"]["carrier"] == "Delta Dental"
    (sarah,) = users["contacts"]
    assert sarah["name"].startswith("Sarah")
    assert sarah["owner_id"] == owner["id"]
    assert sarah["relationship"] == "daughter"
    assert sarah["scope"] == "ride_requests"


def test_every_phone_is_obviously_fake(users: dict, clinics: list[dict]) -> None:
    phones = [users["owner"]["phone_e164"]] + [c["phone_e164"] for c in users["contacts"]]
    phones += [c["phone_e164"] for c in clinics]
    assert len(phones) == 5
    assert len(set(phones)) == 5
    for phone in phones:
        assert FAKE_PHONE.match(phone), phone


def test_three_clinics_with_distances(clinics: list[dict]) -> None:
    by_name = {c["name"]: c for c in clinics}
    assert set(by_name) == {"Bright Smile Dental", "Smile Co.", "Oak Dental"}
    assert by_name["Bright Smile Dental"]["distance_mi"] == 1.2
    assert by_name["Smile Co."]["distance_mi"] == 0.6
    assert by_name["Oak Dental"]["distance_mi"] == 3.4
    for clinic in clinics:
        for key in ("id", "phone_e164", "address", "lat", "lng", "place_id", "drive_min"):
            assert key in clinic, (clinic["name"], key)
        assert "Delta Dental" in clinic["accepts_insurance"]


def test_free_windows_tue_pm_thu_am(windows: dict) -> None:
    assert windows["timezone"] == "America/Chicago"
    assert windows["owner_id"] == "mary"
    labels = {w["label"]: w for w in windows["windows"]}
    assert set(labels) == {"Tue pm", "Thu am"}
    tue, thu = labels["Tue pm"], labels["Thu am"]
    assert tue["start"].endswith("T13:00:00-06:00") and tue["end"].endswith("T17:00:00-06:00")
    assert thu["start"].endswith("T08:00:00-06:00") and thu["end"].endswith("T12:00:00-06:00")
    assert tue["start"][:10] == "2026-11-24" and thu["start"][:10] == "2026-11-26"


def test_receptionists_match_clinics_and_prices(clinics: list[dict], receptionists: list[dict]) -> None:
    assert load("receptionists.json")["simulated"] is True
    assert {r["clinic_id"] for r in receptionists} == {c["id"] for c in clinics}
    results = {r["clinic_id"]: r["result"] for r in receptionists}
    assert (results["bright_smile"]["price_usd"], results["bright_smile"]["slot_label"]) == (95, "Thu 9:30")
    assert (results["smile_co"]["price_usd"], results["smile_co"]["slot_label"]) == (120, "Fri 4:00")
    assert (results["oak_dental"]["price_usd"], results["oak_dental"]["slot_label"]) == (140, "Mon 10:00")
    for result in results.values():
        assert result["insured"] is True
        assert result["slot_start"] < result["slot_end"]
    for r in receptionists:
        assert r["booking_reply"]["status"] in {"confirmed", "tentative", "rejected"}


def test_receptionist_scripts_produce_prototype_lines(receptionists: list[dict]) -> None:
    lines = {r["clinic_id"]: [(ln["speaker"], ln["text"]) for ln in r["lines"]] for r in receptionists}
    opening = "Hi, I'm an AI assistant calling for a patient."
    assert lines["bright_smile"][0] == ("agent", f"{opening} Do you take Delta Dental?")
    assert lines["smile_co"][0] == ("agent", f"{opening} Any cleanings open this week?")
    assert ("clinic", "Yes, we do. A cleaning is $95 with Delta.") in lines["bright_smile"]
    assert ("clinic", "Thursday at 9:30 is open.") in lines["bright_smile"]
    assert ("clinic", "Our next opening is Friday at 4. It's $120 with Delta.") in lines["smile_co"]
    assert ("clinic", "We take Delta. We're $140, earliest is next Monday.") in lines["oak_dental"]
    for r in receptionists:
        for ln in r["lines"]:
            assert ln["speaker"] in {"agent", "clinic"}
        at = [ln["at_ms"] for ln in r["lines"]]
        assert at == sorted(at)
        statuses = [s["status"] for s in r["status_changes"]]
        assert statuses[0] == "dialing" and statuses[-1] == "done"
        assert set(statuses) <= {"dialing", "live", "hold", "done"}
        assert r["status_changes"][-1]["at_ms"] > at[-1], "the call ends after its last line"


def test_agent_discloses_ai_speaks_only_redacted_facts_and_books_nothing(receptionists: list[dict]) -> None:
    """Product rules 1, 2 and 5: AI disclosure on every call, no owner name, no hold or booking before approval."""
    for r in receptionists:
        agent_lines = [ln["text"] for ln in r["lines"] if ln["speaker"] == "agent"]
        assert any(t.startswith("Hi, I'm an AI assistant calling for a patient.") for t in agent_lines), r["clinic_id"]
        for text in agent_lines:
            low = text.lower()
            assert "mary" not in low and "johnson" not in low, (r["clinic_id"], text)
            assert "hold that" not in low and "book it" not in low and "reserve" not in low, (r["clinic_id"], text)
