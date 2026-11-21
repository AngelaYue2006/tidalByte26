"""VOICE_MODE=mock without the receptionist simulator: replay backend/fixtures/receptionists.json with its own timing.

This is the default voice path until integrations/voice_mock (#13) lands, and the fallback after it if that module is
missing. It emits the same `call_status`, `transcript` and `call_result` payloads the simulator does, every one
`simulated: true`, and never dials anything. Prices, slots and insurance come from the fixture's structured `result`,
never from the transcript lines.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from app.ranking import fits_windows, money, slot_label
from integrations.types import CallSpec, Confirmation, Offer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
Sleep = Callable[[float], Awaitable[None]]


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FixtureReplay:
    """Three scripted receptionists, replayed concurrently with the fixture's `at_ms` timing (`sleep` is injectable)."""

    def __init__(self, sleep: Sleep = asyncio.sleep) -> None:
        self.sleep = sleep
        self._scripts = {r["clinic_id"]: r for r in _fixture("receptionists.json")["receptionists"]}
        self._clinics = {c["place_id"]: c for c in _fixture("clinics.json")["clinics"]}

    def _script(self, spec: CallSpec) -> tuple[dict, dict]:
        clinic = self._clinics.get(spec.clinic.place_id)
        if clinic is None or clinic["id"] not in self._scripts:
            raise RuntimeError(f"no receptionist script for {spec.clinic.name}")
        return clinic, self._scripts[clinic["id"]]

    def offer_for(self, spec: CallSpec) -> Offer:
        clinic, script = self._script(spec)
        result = script["result"]
        return Offer(
            call_id=spec.call_id, clinic=spec.clinic.name, price=result["price_usd"],
            slot_start=datetime.fromisoformat(result["slot_start"]), slot_end=datetime.fromisoformat(result["slot_end"]),
            insured=result["insured"], distance_mi=clinic["distance_mi"], drive_min=clinic["drive_min"],
        )

    def timeline(self, spec: CallSpec) -> list[tuple[int, dict]]:
        """(at_ms, payload) for one call: status changes, transcript lines, then the structured result just before `done`."""
        _, script = self._script(spec)
        offer = self.offer_for(spec)
        events = [(s["at_ms"], {"type": "call_status", "call_id": spec.call_id, "status": s["status"], "simulated": True}) for s in script["status_changes"]]
        events += [(ln["at_ms"], {"type": "transcript", "call_id": spec.call_id, "speaker": ln["speaker"], "text": ln["text"], "simulated": True}) for ln in script["lines"]]
        done_at = script["status_changes"][-1]["at_ms"]
        events.append((done_at - 1, {"type": "call_result", "call_id": spec.call_id, "price": money(offer.price), "slot": slot_label(offer.slot_start),
                                     "insured": offer.insured, "slotOk": fits_windows(offer, spec.windows), "simulated": True}))
        return sorted(events, key=lambda item: item[0])

    async def _replay(self, spec: CallSpec, on_event: Callable[[dict], object]) -> Offer:
        elapsed = 0
        for at_ms, payload in self.timeline(spec):
            await self.sleep(max(0, at_ms - elapsed) / 1000)
            elapsed = at_ms
            on_event(payload)
        return self.offer_for(spec)

    async def call_clinics(self, specs: list[CallSpec], on_event: Callable[[dict], object]) -> list[Offer]:
        return list(await asyncio.gather(*(self._replay(spec, on_event) for spec in specs)))

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        _, script = self._script(spec)
        result, reply = script["result"], script["booking_reply"]
        if slot.get("slot_start") != result["slot_start"]:
            raise RuntimeError("requested slot does not match the offer the receptionist made")
        ref = f"mock-booking-{spec.call_id}" if reply["status"] == "confirmed" else None
        return Confirmation(status=reply["status"], confirmation_ref=ref, evidence="Simulated receptionist: " + reply["evidence"], simulated=True)
