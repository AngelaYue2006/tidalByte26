"""Routes computeRoutes distance/time facts; no invented driving estimates."""

import math
import re

from integrations.maps_google_api import MapsError
from integrations.types import Distance


def waypoint(origin):
    if isinstance(origin, str) and origin.strip():
        return {"address": origin}
    if isinstance(origin, dict):
        lat, lng = origin.get("lat"), origin.get("lng")
    elif isinstance(origin, (list, tuple)) and len(origin) == 2:
        lat, lng = origin
    else:
        raise RuntimeError("Route origin requires an address or latitude/longitude")
    if (
        isinstance(lat, bool)
        or isinstance(lng, bool)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
        or not math.isfinite(lat)
        or not math.isfinite(lng)
        or not -90 <= lat <= 90
        or not -180 <= lng <= 180
    ):
        raise RuntimeError("Route origin requires valid latitude/longitude")
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def route(client, origin_waypoint, clinic):
    data = client.request(
        "POST",
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        "routes.distanceMeters,routes.duration",
        {
            "origin": origin_waypoint,
            "destination": waypoint((clinic.lat, clinic.lng)),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
        },
    )
    try:
        row = data["routes"][0]
        if not isinstance(row, dict):
            raise TypeError("Invalid route")
        meters, duration = row.get("distanceMeters", 0), row.get("duration")
        if (
            isinstance(meters, bool)
            or not isinstance(meters, (int, float))
            or not math.isfinite(meters)
            or meters < 0
            or not isinstance(duration, str)
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?s", duration)
        ):
            raise ValueError("Invalid route")
        # Protobuf JSON omits default zero distanceMeters for a zero-length route.
        return Distance(
            place_id=clinic.place_id,
            miles=meters / 1609.344,
            minutes=float(duration[:-1]) / 60,
            simulated=False,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        raise MapsError("Google Routes returned no usable driving route") from None
