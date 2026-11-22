"""Demo reset: stop every pipeline, wipe every table, reseed the contacts and two finished runs for the history page.

The two past runs come from backend/fixtures/past_runs.json and are written as the live pipeline would have written
them: the same task columns, call rows, event trail and visibilities, every voice and transport fact `simulated: true`.
Only `APP_ENV=development` may call this (routers/demo.py); the run is one transaction per table group, in FK order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete
from sqlmodel import Session

from app import texts
from app.db import session_scope
from app.events import EventBus
from app.models import Call, Contact, Event, Receipt, Task, Turn
from app.nemotron.types import IntakeRequest
from app.orchestrator import BOOKING_KEYS, CALL_IDS
from app.people import ensure_contacts, load_owner
from app.ranking import fits_windows, money, slot_label
from integrations.types import Offer, Window

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# Children before parents: receipts, events, turns, calls hang off tasks; contacts stand alone.
WIPE_ORDER = (Receipt, Event, Turn, Call, Contact, Task)


def reset(engine: Engine, pipeline, bus: EventBus, *, now: datetime | None = None) -> dict:
    """Cancel running pipelines, delete every row, reseed. Returns what was stopped, cleared and seeded."""
    stopped = pipeline.reset()
    cleared: dict[str, int] = {}
    with session_scope(engine) as session:
        for model in WIPE_ORDER:
            cleared[model.__tablename__] = session.exec(delete(model)).rowcount  # type: ignore[arg-type]
    seeded = seed(engine, now=now)
    bus.publish_reset()  # every open stream re-sends a snapshot from the empty-then-reseeded tables
    return {"stopped": stopped, "cleared": cleared, "seeded": seeded}


def seed(engine: Engine, *, now: datetime | None = None) -> dict:
    """Contacts from users.json and the past runs from past_runs.json. Idempotent: a run whose id exists is skipped."""
    now = now or datetime.now(UTC)
    fixture = json.loads((FIXTURES / "past_runs.json").read_text(encoding="utf-8"))
    clinics = {c["id"]: c for c in json.loads((FIXTURES / "clinics.json").read_text(encoding="utf-8"))["clinics"]}  # fixture rows, not the adapter type
    seeded_tasks = 0
    with session_scope(engine) as session:
        owner_ids = {run.get("owner_id", "mary") for run in fixture["runs"]}
        contacts = sum(len(ensure_contacts(session, owner_id)) for owner_id in owner_ids)
        for run in fixture["runs"]:
            if session.get(Task, run["id"]) is None:
                _seed_run(session, run, clinics, now)
                seeded_tasks += 1
    return {"tasks": seeded_tasks, "contacts": contacts}


def _seed_run(session: Session, run: dict, clinics: dict[str, dict], now: datetime) -> None:
    owner = load_owner(run.get("owner_id", "mary"))
    first = owner.name.split()[0]
    contact = next((c for c in ensure_contacts(session, owner.id) if c.scope == "ride_requests"), None)
    started = now - timedelta(days=run["days_ago"])
    intake = IntakeRequest.model_validate(run["intake"])
    windows = [Window.model_validate(w) for w in run["windows"]]
    task_id = run["id"]
    offers: dict[str, Offer] = {}
    clinic_of: dict[str, dict] = {}  # call id -> the clinic fixture row
    scores: dict[str, float] = {}
    for letter, call in zip(CALL_IDS, run["calls"], strict=False):
        call_id = f"{task_id[:8]}-{letter}"  # the same shape the pipeline gives a call: task prefix plus a letter
        clinic = clinic_of[call_id] = clinics[call["clinic_id"]]
        offers[call_id] = Offer(call_id=call_id, clinic=clinic["name"], price=call["price_usd"], slot_start=call["slot_start"], slot_end=call["slot_end"],
                                insured=call["insured"], distance_mi=clinic["distance_mi"], drive_min=clinic["drive_min"])
        scores[call_id] = call["score"]
    winner = next(o for o in offers.values() if o.clinic == clinics[run["winner"]]["name"])
    address = clinics[run["winner"]]["address"]
    decision = {"winner_call_id": winner.call_id, "score": scores[winner.call_id], "reasons": run["decision"]["reasons"], "second": run["decision"]["second"],
                "tradeoff": run["decision"]["tradeoff"], "ranked": sorted(({"call_id": cid, "score": s} for cid, s in scores.items()), key=lambda r: -r["score"])}
    booking = {"clinic": winner.clinic, "slot_start": winner.slot_start.isoformat(), "slot_end": winner.slot_end.isoformat(), "price": money(winner.price), **run["booking"]}
    booking = {key: booking.get(key) for key in BOOKING_KEYS}
    ride = run.get("ride") if intake.needs_ride else None
    finished = started + timedelta(minutes=6 if ride else 3)

    session.add(Task(id=task_id, owner_id=owner.id, status="completed", intake_json=intake.model_dump_json(),
                     windows_json=json.dumps([{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in windows]),
                     decision_json=json.dumps(decision), booking_json=json.dumps(booking), transport_json=json.dumps(run["transport"]),
                     created_at=started, updated_at=finished))
    for call_id, offer in offers.items():
        clinic = clinic_of[call_id]
        session.add(Call(id=call_id, task_id=task_id, clinic_name=offer.clinic, clinic_phone=clinic["phone_e164"], distance_mi=clinic["distance_mi"], status="done",
                         result_json=json.dumps({"price": money(offer.price), "slot": slot_label(offer.slot_start), "insured": offer.insured, "slotOk": fits_windows(offer, windows)}),
                         started_at=started + timedelta(seconds=20), ended_at=started + timedelta(seconds=80)))

    trail: list[tuple[str, dict, str]] = [
        ("task_updated", {"status": "intake"}, "contact"),
        ("task_updated", {"status": "calendar"}, "contact"),
        ("request", {"text": run["text"], "chips": texts.chips(intake.care_type, intake.budget_max, intake.insurance_carrier, windows)}, "contact"),
        ("task_updated", {"status": "places"}, "contact"),
    ]
    for call_id, offer in offers.items():
        clinic = clinic_of[call_id]
        trail.append(("call_start", {"call_id": call_id, "clinic": offer.clinic, "meta": f"{clinic['distance_mi']:g} mi · {clinic['drive_min']:g} min", "simulated": True}, "contact"))
    trail.append(("task_updated", {"status": "calling"}, "contact"))
    for call_id, offer in offers.items():
        trail += [
            ("call_status", {"call_id": call_id, "status": "live", "simulated": True}, "contact"),
            ("call_result", {"call_id": call_id, "price": money(offer.price), "slot": slot_label(offer.slot_start), "insured": offer.insured, "slotOk": fits_windows(offer, windows), "simulated": True}, "contact"),
            ("call_status", {"call_id": call_id, "status": "done", "simulated": True}, "contact"),
        ]
    trail += [
        ("task_updated", {"status": "ranking"}, "contact"),
        ("decision", {"winner": winner.call_id, "title": f"Why Nemotron picked {winner.clinic}", "reasons": decision["reasons"], "second": decision["second"], "tradeoff": decision["tradeoff"]}, "contact"),
        ("task_updated", {"status": "awaiting_approval"}, "contact"),
        ("approval_required", {"pick": {"clinic": winner.clinic, "slot": slot_label(winner.slot_start), "price": money(winner.price)}, "expires_at": (started + timedelta(minutes=12)).isoformat()}, "contact"),
        ("approved", {"by": owner.id, "via": "dashboard"}, "contact"),
        ("task_updated", {"status": "booking"}, "contact"),
        ("booked", {"calendar": texts.calendar_card(winner.slot_start, winner.slot_end, address),
                    "sms_user": texts.booked_sms(winner.clinic, winner.slot_start, winner.price, intake.insurance_carrier), "simulated": True}, "contact"),
        ("task_updated", {"status": "transport"}, "contact"),
        ("transport_check", {"status": "checking", "reason": "", "simulated": True}, "contact"),
        ("transport_check", {"status": "available" if run["transport"]["available"] else "unavailable", "reason": run["transport"]["reason"], "simulated": True}, "contact"),
    ]
    if ride and contact:
        driver = contact.name.split()[0]
        trail += [
            ("task_updated", {"status": "awaiting_contact"}, "contact"),
            ("contact_request", {"contact": driver, "message": texts.contact_request_message(driver, first, intake.care_type, winner.clinic, winner.slot_start, address)}, "contact"),
            ("contact_reply", {"contact": driver, "text": "I can drive.", "offer": {"can_drive": True}}, "contact"),
            ("ride_confirmed", {"driver": driver, "pickup_time": ride["pickup_time"]}, "contact"),
            ("notified", {"sms_contact": texts.ride_confirmed_sms_contact(first, winner.clinic, winner.slot_start),
                          "sms_user": texts.ride_confirmed_sms_user(driver, winner.clinic, winner.slot_start), "simulated": True}, "contact"),
        ]
    else:
        trail.append(("notified", {"sms_contact": texts.no_ride_needed_sms_contact(first, winner.clinic, winner.slot_start, address) if contact else "",
                                   "sms_user": texts.booked_sms(winner.clinic, winner.slot_start, winner.price, intake.insurance_carrier), "simulated": True}, "contact"))
    trail.append(("task_updated", {"status": "completed"}, "contact"))
    step = (finished - started) / (len(trail) + 1)
    for index, (type_, payload, visibility) in enumerate(trail, start=1):
        session.add(Event(task_id=task_id, type=type_, payload_json=json.dumps(payload, ensure_ascii=False), visibility=visibility, at=started + step * index))
