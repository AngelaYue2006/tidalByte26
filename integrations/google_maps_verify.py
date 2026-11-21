"""Verify Places (New) and Routes access using only synthetic demo queries."""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values


def post_json(url, body, key, mask):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": mask,
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def location(lat, lng):
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def verify(key):
    places = post_json(
        "https://places.googleapis.com/v1/places:searchText",
        {"textQuery": "dental cleaning near Chicago, IL", "pageSize": 3},
        key,
        "places.id",
    )
    print("Places text search: succeeded; result count:", len(places.get("places", [])))
    routes = post_json(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        {
            "origin": location(41.8842, -87.6324),
            "destination": location(41.8925, -87.6240),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
        },
        key,
        "routes.distanceMeters,routes.duration",
    ).get("routes", [])
    valid = bool(routes) and all(
        "distanceMeters" in route and "duration" in route for route in routes
    )
    print("Routes computeRoutes driving metrics verified:", valid)
    return 0 if places.get("places") and valid else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        key = dotenv_values(args.env_file).get("GOOGLE_MAPS_API_KEY")
        if not key:
            print("Set GOOGLE_MAPS_API_KEY in the local .env first.")
            return 1
        return verify(key)
    except urllib.error.HTTPError as error:
        print("Google Maps HTTP status:", error.code)
        try:
            payload = json.load(error)
            for item in payload if isinstance(payload, list) else [payload]:
                details = item.get("error", {})
                print("Google error status:", details.get("status", "unknown"))
                for detail in details.get("details", []):
                    if detail.get("reason"):
                        print("Google error reason:", detail["reason"])
        except (ValueError, AttributeError, TypeError):
            print("Structured error unavailable")
    except Exception as error:  # noqa: BLE001 - never print credential-bearing exceptions
        print("Maps verification stopped:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
