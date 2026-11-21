"""Typed clinic discovery with fixture and demo-safe live Places modes."""

import os

from integrations.fixtures import read_fixture
from integrations.types import Clinic


def find_clinics(care_type, area, limit=3) -> list[Clinic]:
    if (
        not isinstance(care_type, str)
        or not care_type.strip()
        or not isinstance(area, str)
        or not area.strip()
        or isinstance(limit, bool)
        or not isinstance(limit, int)
    ):
        raise RuntimeError(
            "Clinic search requires care type, area and an integer limit"
        )
    if limit < 0:
        raise RuntimeError("Clinic limit cannot be negative")
    mode = os.getenv("PLACES_MODE", "fixture")
    if mode not in ("fixture", "live"):
        raise RuntimeError("PLACES_MODE must be fixture or live")
    if mode == "live":
        if limit > 3:
            raise RuntimeError("Live clinic limit cannot exceed three")
        if limit == 0:
            return []
        from integrations.places_live import find

        return find(care_type.strip(), area.strip(), limit)
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
