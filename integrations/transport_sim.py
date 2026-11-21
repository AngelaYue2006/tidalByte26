"""Always-simulated transport adapter; never books a ride."""

import json
import os
from pathlib import Path

from integrations.types import Booking, TransportOptions


def check(booking: Booking, needs: dict) -> TransportOptions:
    if os.getenv("TRANSPORT_MODE", "fixture") != "fixture":
        raise RuntimeError("Transport only supports TRANSPORT_MODE=fixture")
    if booking.status == "rejected":
        raise RuntimeError("Transport check cannot use a rejected booking")
    path = Path(__file__).resolve().parent / "fixtures" / "transport.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data != {
        "available": False,
        "reason": "UNAVAILABLE_ACCESSIBLE_RIDE",
        "simulated": True,
    }:
        raise RuntimeError(
            "Transport fixture must describe a simulated unavailable ride"
        )
    return TransportOptions(**data)
