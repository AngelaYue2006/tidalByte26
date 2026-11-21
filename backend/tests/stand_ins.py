"""Test-only stand-ins for the parts the mocked pipeline cannot run in a test: Nano, Super and the receptionist simulator.

FakeVoice replays backend/fixtures/receptionists.json the way integrations/voice_mock (#13) will, emitting the same
`call_status`, `transcript` and `call_result` payloads with simulated=true, without the wall-clock delays.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.ranking import fits_windows, money, slot_label

from integrations.types import CallSpec, Confirmation, Offer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RECEPTIONISTS = {r["clinic_id"]: r for r in json.loads((FIXTURES / "receptionists.json").read_text())["receptionists"]}
CLINICS = {c["id"]: c for c in json.loads((FIXTURES / "clinics.json").read_text())["clinics"]}

DEMO_TEXT = "I need a dental cleaning this week, under $150. I have Delta Dental. My knee makes walking hard so I'll need a ride."
DEMO_INTAKE = {
    "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental", "time_phrase": "this week",
    "needs_ride": True, "search_area": "near home", "dropped_fields": ["mobility_details"],
}


class FakeNano:
    """Answers the intake prompt with a fixed redacted proposal."""

    name = "fake-nano"

    def __init__(self, proposal: dict | None = None) -> None:
        self.proposal = proposal or DEMO_INTAKE

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        return dict(self.proposal)


class FakeSuper:
    """Picks the cheapest eligible offer and writes a templated trade-off, in the JSON shape the ranker checks."""

    model_id = "fake-super"

    def complete_json(self, system: str, user: str, *, previous=None) -> str:
        facts = json.loads(user[user.index("{") : user.rindex("}") + 1]) if "{" in user else {}
        offers = facts.get("offers") or []
        ranked = sorted(offers, key=lambda o: (o.get("price", 0), o.get("slot_start", "")))
        if not ranked:
            return json.dumps({"winner_call_id": "a", "ranked": [{"call_id": "a", "score": 90}], "tradeoff": "Only one option fit."})
        scores = [{"call_id": o["call_id"], "score": 95 - 10 * i} for i, o in enumerate(ranked)]
        runner = ranked[1]["clinic"] if len(ranked) > 1 else "no other clinic"
        return json.dumps({"winner_call_id": ranked[0]["call_id"], "ranked": scores,
                           "tradeoff": f"{runner} was the alternative, but {ranked[0]['clinic']} costs less and fits your free time."})


class FakeVoice:
    """The receptionist simulator's contract, replayed instantly from the fixture scripts."""

    def __init__(self, booking_status: str | None = None, price_override: dict[str, float] | None = None) -> None:
        self.booking_status = booking_status  # force confirmed | tentative | rejected for every clinic
        self.price_override = price_override or {}
        self.confirmed: list[str] = []
        self.started: list[str] = []

    def _script(self, spec: CallSpec) -> dict:
        clinic_id = spec.clinic.id or next(c["id"] for c in CLINICS.values() if c["place_id"] == spec.clinic.place_id)
        return RECEPTIONISTS[clinic_id]

    async def call_clinics(self, specs: list[CallSpec], on_event) -> list[Offer]:
        offers = []
        for spec in specs:
            self.started.append(spec.call_id)
            script = self._script(spec)
            result = script["result"]
            price = self.price_override.get(spec.clinic.name, result["price_usd"])
            start, end = datetime.fromisoformat(result["slot_start"]), datetime.fromisoformat(result["slot_end"])
            offer = Offer(call_id=spec.call_id, clinic=spec.clinic.name, price=price, slot_start=start, slot_end=end, insured=result["insured"],
                          distance_mi=CLINICS[self._script(spec)["clinic_id"]]["distance_mi"], drive_min=CLINICS[self._script(spec)["clinic_id"]]["drive_min"])
            timeline = [(s["at_ms"], {"type": "call_status", "call_id": spec.call_id, "status": s["status"], "simulated": True}) for s in script["status_changes"]]
            timeline += [(ln["at_ms"], {"type": "transcript", "call_id": spec.call_id, "speaker": ln["speaker"], "text": ln["text"], "simulated": True}) for ln in script["lines"]]
            done_at = script["status_changes"][-1]["at_ms"]
            timeline.append((done_at - 1, {"type": "call_result", "call_id": spec.call_id, "price": money(price), "slot": slot_label(start),
                                           "insured": result["insured"], "slotOk": fits_windows(offer, spec.windows), "simulated": True}))
            for _, event in sorted(timeline, key=lambda t: t[0]):
                on_event(event)
            offers.append(offer)
        return offers

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        self.confirmed.append(spec.call_id)
        reply = self._script(spec)["booking_reply"]
        status = self.booking_status or reply["status"]
        return Confirmation(status=status, confirmation_ref=f"fake-booking-{spec.call_id}" if status == "confirmed" else None,
                            evidence="Simulated receptionist: " + reply["evidence"], simulated=True)
