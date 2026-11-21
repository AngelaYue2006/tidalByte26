"""Test-only stand-ins for the two Nemotron services the mocked pipeline cannot call in a test.

Voice is not stubbed: tests run the default `VoiceMockBridge`, which replays backend/fixtures/receptionists.json
(app/voice_replay.py), with an instant `sleep` so the fixture's timing does not slow the suite.
"""

from __future__ import annotations

import json

DEMO_TEXT = "I need a dental cleaning this week, under $150. I have Delta Dental. My knee makes walking hard so I'll need a ride."
DEMO_INTAKE = {
    "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental", "time_phrase": "this week",
    "needs_ride": True, "search_area": "near home", "dropped_fields": ["mobility_details"],
}


async def instant(_seconds: float) -> None:
    """Stands in for asyncio.sleep: the fixture timing is honoured in order, not in wall-clock."""


class FakeNano:
    """Answers the intake prompt with a fixed redacted proposal, and the contact prompt with a scoped message built
    from the appointment facts in the record (or `contact_message`, to test the check)."""

    name = "fake-nano"

    def __init__(self, proposal: dict | None = None, contact_message: str | None = None) -> None:
        self.proposal = proposal or DEMO_INTAKE
        self.contact_message = contact_message
        self.contact_records: list[dict] = []  # what the contact prompt was given, for the no-leak test

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        if "message" in schema.get("properties", {}):
            record = json.loads(user)
            self.contact_records.append(record)
            if self.contact_message is not None:
                return {"message": self.contact_message}
            a = record["appointment"]
            return {"message": (f"Hi {record['contact']['first_name']}, {a['owner_first_name']} has a {a['for']} at {a['clinic']} on {a['when']}, "
                                f"{a['address']}. No accessible ride was found. Can you drive? Reply YES or NO.")}
        return dict(self.proposal)


class FakeSuper:
    """Picks the cheapest eligible offer and writes a templated trade-off, in the JSON shape the ranker checks."""

    model_id = "fake-super"

    def complete_json(self, system: str, user: str, *, previous=None) -> str:
        facts = json.loads(user[user.index("{") : user.rindex("}") + 1]) if "{" in user else {}
        offers = facts.get("offers") or []
        ranked = sorted(offers, key=lambda o: (o.get("price", 0), o.get("slot_start", "")))
        if not ranked:
            return json.dumps({"winner_call_id": "?", "ranked": [], "tradeoff": "Only one option fit."})
        scores = [{"call_id": o["call_id"], "score": 95 - 10 * i} for i, o in enumerate(ranked)]
        runner = ranked[1]["clinic"] if len(ranked) > 1 else "no other clinic"
        return json.dumps({"winner_call_id": ranked[0]["call_id"], "ranked": scores,
                           "tradeoff": f"{runner} was the alternative, but {ranked[0]['clinic']} costs less and fits your free time."})
