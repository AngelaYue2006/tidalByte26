"""Places discovery with mandatory demo phone substitution before facts escape."""

import logging
import os
import re
from urllib.parse import quote

from pydantic import ValidationError

from integrations.maps_google_api import MapsClient, MapsError
from integrations.phone_policy import require_allowlisted
from integrations.types import Clinic

logger = logging.getLogger(__name__)
DETAIL_FIELDS = "id,displayName,formattedAddress,location,internationalPhoneNumber"


def demo_phones(limit):
    # Preserve configured order and avoid assigning the same teammate twice.
    phones = list(
        dict.fromkeys(
            p.strip()
            for p in os.getenv("DEMO_PHONE_ALLOWLIST", "").split(",")
            if p.strip()
        )
    )
    if len(phones) < limit:
        raise RuntimeError(
            "Live discovery requires one allowlisted demo phone per clinic"
        )
    for phone in phones[:limit]:
        require_allowlisted(phone)
    return phones[:limit]


def find(care_type, area, limit):
    phones = demo_phones(limit)
    with MapsClient() as client:
        data = client.request(
            "POST",
            "https://places.googleapis.com/v1/places:searchText",
            "places.id",
            {"textQuery": f"{care_type} near {area}", "pageSize": limit},
        )
        rows = data.get("places", [])
        if not isinstance(rows, list):
            raise MapsError("Google Places returned invalid search results")
        clinics = []
        seen = set()
        for row in rows[:limit]:
            place_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(place_id, str) or not place_id or place_id in seen:
                raise MapsError(
                    "Google Places returned an invalid or duplicate place ID"
                )
            seen.add(place_id)
            details = client.request(
                "GET",
                "https://places.googleapis.com/v1/places/" + quote(place_id, safe=""),
                DETAIL_FIELDS,
            )
            # Check the source phone's E.164 shape, then discard it. It is never returned.
            source_phone = re.sub(
                r"[ ()\-]", "", str(details.get("internationalPhoneNumber", ""))
            )
            if not re.fullmatch(r"\+[1-9]\d{7,14}", source_phone):
                raise MapsError(
                    "Google Places detail is missing a valid international phone"
                )
            try:
                if details["id"] != place_id:
                    raise ValueError("Mismatched place")
                clinic = Clinic(
                    name=details["displayName"]["text"],
                    phone_e164=phones[len(clinics)],
                    address=details["formattedAddress"],
                    lat=details["location"]["latitude"],
                    lng=details["location"]["longitude"],
                    place_id=place_id,
                    simulated=True,
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                raise MapsError(
                    "Google Places returned incomplete clinic details"
                ) from None
            require_allowlisted(clinic.phone_e164)
            clinics.append(clinic)
    # No phone values, search text, addresses, or vendor response content in logs.
    logger.info(
        "Demo clinic phone substitution applied; clinics=%d simulated=true",
        len(clinics),
    )
    return clinics
