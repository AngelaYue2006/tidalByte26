"""Distances from the fixture origin, preserving the requested clinic order."""

import os

from integrations.fixtures import read_fixture
from integrations.types import Clinic, Distance


def drive(origin, clinics: list[Clinic]) -> list[Distance]:
    if os.getenv("PLACES_MODE", "fixture") != "fixture":
        raise RuntimeError(
            "Distance live mode is not implemented; use PLACES_MODE=fixture"
        )
    home = read_fixture("users.json")["owner"]["home"]
    valid_origin = origin == home["address"] or origin == home
    if isinstance(origin, (tuple, list)):
        valid_origin = list(origin) == [home["lat"], home["lng"]]
    if not valid_origin:
        raise RuntimeError("Distance fixture only supports the synthetic owner's home")
    rows = {row["place_id"]: row for row in read_fixture("clinics.json")["clinics"]}
    result = []
    for clinic in clinics:
        if clinic.place_id not in rows:
            raise RuntimeError("Distance fixture has no route for this clinic")
        row = rows[clinic.place_id]
        result.append(
            Distance(
                place_id=clinic.place_id,
                miles=row["distance_mi"],
                minutes=row["drive_min"],
                simulated=True,
            )
        )
    return result
