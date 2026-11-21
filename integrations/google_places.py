"""Fixture clinic discovery; no network calls or real clinic lookups."""

import os

from integrations.fixtures import read_fixture
from integrations.types import Clinic


def find_clinics(care_type, area, limit=3) -> list[Clinic]:
    if os.getenv("PLACES_MODE", "fixture") != "fixture":
        raise RuntimeError(
            "Places live mode is not implemented; use PLACES_MODE=fixture"
        )
    if (
        not care_type
        or not area
        or isinstance(limit, bool)
        or not isinstance(limit, int)
    ):
        raise RuntimeError(
            "Clinic search requires care type, area and an integer limit"
        )
    if limit < 0:
        raise RuntimeError("Clinic limit cannot be negative")
    fixture = read_fixture("clinics.json")
    if care_type.casefold() != fixture["care_type"].casefold():
        return []
    if area.casefold() not in (fixture["search_area"].casefold(), "near home"):
        return []
    fields = ("id", "name", "phone_e164", "address", "lat", "lng", "place_id")
    return [
        Clinic(**{key: row[key] for key in fields}, simulated=True)
        for row in fixture["clinics"][:limit]
    ]
