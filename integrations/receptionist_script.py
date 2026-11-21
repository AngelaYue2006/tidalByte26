"""Compile synthetic receptionist fixtures into timed events and structured facts."""

from dataclasses import dataclass
from datetime import datetime

from integrations.fixtures import read_fixture
from integrations.types import CallSpec, Offer, Window

DISCLOSURE = "Hi, I'm an AI assistant calling for a patient."


@dataclass(frozen=True)
class ReplayPlan:
    events: tuple[tuple[int, dict], ...]
    offer: Offer


def script_for(call: CallSpec) -> tuple[dict, dict]:
    clinics = read_fixture("clinics.json")["clinics"]
    clinic = next((c for c in clinics if c["place_id"] == call.clinic.place_id), None)
    if clinic is None or (
        call.clinic.id is not None and call.clinic.id != clinic["id"]
    ):
        raise RuntimeError("No synthetic receptionist matches this clinic")
    fixture = read_fixture("receptionists.json")
    if fixture.get("simulated") is not True:
        raise RuntimeError("Receptionist fixture must be explicitly simulated")
    script = next(
        (s for s in fixture["receptionists"] if s["clinic_id"] == clinic["id"]), None
    )
    if script is None:
        raise RuntimeError("No synthetic receptionist script for this clinic")
    agent_lines = [line for line in script["lines"] if line["speaker"] == "agent"]
    if not agent_lines or not agent_lines[0]["text"].startswith(DISCLOSURE):
        raise RuntimeError("Receptionist script must open with an AI disclosure")
    return clinic, script


def build_plan(call: CallSpec) -> ReplayPlan:
    clinic, script = script_for(call)
    result = script["result"]
    offer = Offer(
        call_id=call.call_id,
        clinic=call.clinic.name,
        price=result["price_usd"],
        slot_start=result["slot_start"],
        slot_end=result["slot_end"],
        insured=result["insured"],
        distance_mi=clinic["distance_mi"],
        drive_min=clinic["drive_min"],
    )
    slot = Window(start=offer.slot_start, end=offer.slot_end)
    base = {"call_id": call.call_id, "simulated": True}
    events = []
    for status in script["status_changes"]:
        if status["status"] not in {"dialing", "live", "hold", "done"}:
            raise RuntimeError("Unknown synthetic call status")
        events.append(
            (
                status["at_ms"],
                {**base, "type": "call_status", "status": status["status"]},
            )
        )
    for line in script["lines"]:
        if line["speaker"] not in {"agent", "clinic"}:
            raise RuntimeError("Unknown synthetic transcript speaker")
        events.append(
            (
                line["at_ms"],
                {
                    **base,
                    "type": "transcript",
                    "speaker": line["speaker"],
                    "text": line["text"],
                },
            )
        )
    if not events or any(not isinstance(at, int) or at < 0 for at, _ in events):
        raise RuntimeError("Synthetic event times must be nonnegative milliseconds")
    events.sort(key=lambda item: item[0])
    statuses = [
        event["status"] for _, event in events if event["type"] == "call_status"
    ]
    if not statuses or statuses[0] != "dialing" or statuses[-1] != "done":
        raise RuntimeError("Synthetic call must run from dialing to done")
    events.append(
        (
            events[-1][0],
            {
                **base,
                "type": "call_result",
                "price": f"${offer.price:g}",
                "slot": result["slot_label"],
                "insured": offer.insured,
                "slotOk": any(
                    w.start <= slot.start and slot.end <= w.end for w in call.windows
                ),
            },
        )
    )
    return ReplayPlan(events=tuple(events), offer=offer)


def slot_matches(slot, result: dict) -> bool:
    expected = Window(start=result["slot_start"], end=result["slot_end"])
    if isinstance(slot, Window):
        return slot == expected
    if isinstance(slot, dict):
        start = slot.get("start", slot.get("slot_start"))
        end = slot.get("end", slot.get("slot_end"))
        return bool(start and end) and Window(start=start, end=end) == expected
    if isinstance(slot, str) and slot == result["slot_label"]:
        return True
    if isinstance(slot, str):
        try:
            slot = datetime.fromisoformat(slot)
        except ValueError:
            return False
    return isinstance(slot, datetime) and slot == expected.start
