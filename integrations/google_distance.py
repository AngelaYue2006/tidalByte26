"""Fixture or Google driving facts, preserving the requested clinic order."""

import logging
import os

from integrations.fixtures import read_fixture
from integrations.types import Clinic, Distance


def drive(origin, clinics: list[Clinic]) -> list[Distance]:
    mode = os.getenv("PLACES_MODE", "fixture")
    if mode not in ("fixture", "live"):
        raise RuntimeError("PLACES_MODE must be fixture or live")
    if mode == "live":
        return _live_drive(origin, clinics)
    return _fixture_drive(origin, clinics)


def _fixture_drive(origin, clinics):
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


def _live_drive(origin, clinics):
    from integrations.maps_google_api import MapsClient, MapsError
    from integrations.routes_live import route, waypoint

    origin_waypoint = waypoint(origin)
    if not clinics:
        return []
    results = []
    with MapsClient() as client:
        for clinic in clinics:
            try:
                results.append(route(client, origin_waypoint, clinic))
            except MapsError:
                # Owner-approved fixture fallback: never assign synthetic times
                # to an unrelated live clinic or a different origin.
                try:
                    fallback = _fixture_drive(origin, [clinic])[0]
                except RuntimeError:
                    raise RuntimeError(
                        "Driving route unavailable; no matching fixture fallback"
                    ) from None
                logging.getLogger(__name__).warning(
                    "Driving route unavailable; using simulated fixture distance/time"
                )
                results.append(fallback)
    return results
