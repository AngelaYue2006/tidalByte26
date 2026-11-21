"""Deterministic pipeline (docs/ARCHITECTURE.md, Pipeline). Runs steps 1-10, writes events, waits on approval and contact reply. Side effects keyed by task_id + step.

One `Pipeline` per app. `start(task_id, text)` schedules `run` on the server loop; `resume(task_id)` releases a wait.
Every step moves the task through state.transition, persists, and emits `task_updated`; adapters return facts and
the pipeline records them. Nothing is booked and no calendar event is written before the `approved` event.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlmodel import Session

from app import receipts, texts
from app.adapters import Deps
from app.db import session_scope
from app.events import EventBus, emit
from app.models import Call, Task
from app.nemotron import local_intake
from app.nemotron.ranker import timed_rank
from app.nemotron.types import IntakeRequest, UserRecord
from app.people import ensure_contacts, load_owner
from app.ranking import hard_rules, money, no_eligible_offer, slot_label
from app.routers import (
    llm_proxy,  # the one transcript recorder, shared with live calls (#87)
)
from app.state import transition
from integrations.types import (
    Booking,
    CalendarReceipt,
    CallSpec,
    Clinic,
    Confirmation,
    MessageReceipt,
    Offer,
    Window,
)
from integrations.types import IntakeRequest as WireIntakeRequest

log = logging.getLogger(__name__)

DEFAULT_APPROVAL_TIMEOUT_S = 10 * 60  # settings.approval_timeout_min wins; this is the fallback for a bare Pipeline()
CALL_IDS = "abcdefghij"


BOOKING_KEYS = ("clinic", "slot_start", "slot_end", "price", "status", "confirmation_ref", "calendar_event_id")


def booking_record(booking: Booking) -> dict:
    """The booking as shared/task.schema.json documents it: the seven keys, nothing the adapter type adds (such as address)."""
    data = booking.model_dump(mode="json")
    return {key: data.get(key) for key in BOOKING_KEYS}


class PipelineFailure(Exception):
    """A step could not complete. `code` is one of the error codes in docs/ARCHITECTURE.md."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Run:
    task_id: str
    owner: UserRecord
    text: str  # the raw utterance: stays in this process and the on-device events table, never in a log or a network call
    intake: IntakeRequest | None = None
    windows: list[Window] | None = None
    clinics: list[Clinic] | None = None
    specs: dict[str, CallSpec] | None = None
    offers: list[Offer] | None = None
    winner: Offer | None = None
    booking: Booking | None = None
    proxy_specs: dict = field(default_factory=dict)  # call id -> the recorder's CallSpec, loaded once per call
    transcript_seq: dict[str, int] = field(default_factory=dict)  # call id -> last seq given to a line that arrived without one


class Pipeline:
    def __init__(self, deps: Deps, engine: Engine, bus: EventBus, approval_timeout_s: float = DEFAULT_APPROVAL_TIMEOUT_S) -> None:
        self.deps = deps
        self.engine = engine
        self.bus = bus
        self.approval_timeout_s = approval_timeout_s
        self._waits: dict[str, asyncio.Event] = {}
        self._claimed: set[str] = set()
        self._tasks: dict[str, asyncio.Task] = {}
        # Idempotency lives in the receipts table (#24): request keys and per-route replies survive a restart.

    # ---- entry points -------------------------------------------------------------------------------------------

    def start(self, task_id: str, text: str) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(self.run(task_id, text), name=f"pipeline:{task_id}")
        self._tasks[task_id] = task
        return task

    def claim_wait(self, task_id: str) -> bool:
        """Take the one answer a wait accepts. True once; False when nothing is waiting or it was already claimed.

        The routes run on the single server loop with no await between claim and emit, so the claim is atomic.
        """
        if task_id not in self._waits or task_id in self._claimed:
            return False
        self._claimed.add(task_id)
        return True

    def release_wait(self, task_id: str) -> None:
        """Give a claimed wait back after the reply's writes failed, so a retry can take it."""
        self._claimed.discard(task_id)

    def resume(self, task_id: str) -> bool:
        """Release the wait a POST has satisfied. False when nothing is waiting for this task."""
        event = self._waits.get(task_id)
        if event is None:
            return False
        event.set()
        return True

    def waiting(self, task_id: str) -> bool:
        return task_id in self._waits and task_id not in self._claimed

    def replay(self, route: str, task_id: str, key: str) -> dict | None:
        """The reply already given for this (route, task, key), or None. Persisted, so a retry after a restart matches."""
        receipt = receipts.find(self.engine, task_id, f"reply:{route}:{key}")
        return receipts.payload_of(receipt) if receipt else None

    def remember(self, route: str, task_id: str, key: str, response: dict) -> dict:
        receipts.record(self.engine, task_id, f"reply:{route}:{key}", "reply", response)
        return response

    def task_for_request_key(self, key: str) -> str | None:
        """POST /api/requests idempotency: the task a key already created, or None."""
        receipt = receipts.find_by_step(self.engine, f"request:{key}")
        return receipt.task_id if receipt else None

    def remember_request_key(self, key: str, task_id: str) -> None:
        receipts.record(self.engine, task_id, f"request:{key}", "request", {"task_id": task_id})

    def reset(self) -> int:
        """Stop every running pipeline task and forget every wait: POST /api/demo/reset wipes the tables underneath."""
        stopped = 0
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
                stopped += 1
        self._tasks.clear()
        for event in self._waits.values():
            event.set()
        self._waits.clear()
        self._claimed.clear()
        return stopped

    # ---- the ten steps -------------------------------------------------------------------------------------------

    async def run(self, task_id: str, text: str) -> None:
        with Session(self.engine) as session:
            owner_id = session.get(Task, task_id).owner_id
        run = Run(task_id=task_id, owner=load_owner(owner_id), text=text)
        try:
            await self._intake(run, text)
            self._calendar(run)
            self._places(run)
            await self._calling(run)
            await self._ranking(run)
            if not await self._await_approval(run):
                return
            self._booking(run)
            needs_contact = self._transport(run)
            if needs_contact and not await self._await_contact(run):
                return
            self._completed(run)
        except PipelineFailure as failure:
            self._fail(run, failure.code, str(failure))
        except Exception as exc:  # a bug or an adapter error: never a silent completed
            log.exception("pipeline %s crashed", task_id)
            self._fail(run, "CALL_FAILED" if run.offers is None and run.specs else "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
        finally:
            self._tasks.pop(task_id, None)

    async def _intake(self, run: Run, text: str) -> None:
        self._set_status(run, "intake")
        try:
            run.intake = await asyncio.to_thread(local_intake.redact, text, run.owner, model=self.deps.intake_model(), now=self._now(run))
        except local_intake.IntakeError as exc:
            raise PipelineFailure("INTAKE_INCOMPLETE", str(exc)) from exc
        with session_scope(self.engine) as session:
            task = session.get(Task, run.task_id)
            task.intake_json = run.intake.model_dump_json()
            ensure_contacts(session, run.owner.id)
        # chips need the windows; the request event is emitted after the calendar step with everything it shows

    def _calendar(self, run: Run) -> None:
        self._set_status(run, "calendar")
        intake = run.intake
        run.windows = list(self.deps.free_windows(run.owner.id, intake.time_range.start, intake.time_range.end))
        with session_scope(self.engine) as session:
            session.get(Task, run.task_id).windows_json = json.dumps([{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in run.windows])
        self._emit(run, "request", {"text": run.text, "chips": texts.chips(intake.care_type, intake.budget_max, intake.insurance_carrier, run.windows)}, "contact")

    def _places(self, run: Run) -> None:
        self._set_status(run, "places")
        intake = run.intake
        run.clinics = list(self.deps.find_clinics(intake.care_type, intake.search_area or "near home", 3))
        if not run.clinics:
            raise PipelineFailure("NO_CLINICS_FOUND", f"No clinic offering {intake.care_type} was found near {intake.search_area or 'home'}.")
        origin = run.owner.home.address if run.owner.home else "near home"
        distances = {d.place_id: d for d in self.deps.drive(origin, run.clinics)}
        wire_request = WireIntakeRequest(**intake.model_dump(exclude={"time_range"}), time_range=Window(start=intake.time_range.start, end=intake.time_range.end))
        # One id per call, unique across tasks, used everywhere: the calls table, every event, the decision and the snapshot.
        run.specs = {}
        with session_scope(self.engine) as session:
            for letter, clinic in zip(CALL_IDS, run.clinics, strict=False):
                call_id = f"{run.task_id[:8]}-{letter}"
                distance = distances.get(clinic.place_id)
                run.specs[call_id] = CallSpec(clinic=clinic, request=wire_request, windows=run.windows, call_id=call_id)
                session.add(Call(id=call_id, task_id=run.task_id, clinic_name=clinic.name, clinic_phone=clinic.phone_e164,
                                 distance_mi=distance.miles if distance else None, status="dialing", started_at=datetime.now(UTC)))
        for call_id, spec in run.specs.items():
            distance = distances.get(spec.clinic.place_id)
            meta = f"{distance.miles:g} mi · {distance.minutes:g} min" if distance else ""
            self._emit(run, "call_start", {"call_id": call_id, "clinic": spec.clinic.name, "meta": meta, "simulated": spec.clinic.simulated}, "contact")

    async def _calling(self, run: Run) -> None:
        self._set_status(run, "calling")
        offers = await self.deps.voice.call_clinics(list(run.specs.values()), lambda event: self._voice_event(run, event))
        run.offers = list(offers)
        if not run.offers:
            raise PipelineFailure("CALL_FAILED", "No clinic call produced an offer.")

    def _voice_event(self, run: Run, event: dict) -> None:
        """A `call_status`, `transcript` or `call_result` payload from the voice adapter: record the fact, then emit.

        Transcript lines do not emit here: they take the live recorder (`_record_transcript`), so a mock call leaves
        the same Turn rows and transcript events a real call does."""
        event = dict(event)
        type_ = event.pop("type")
        call_id = event.get("call_id")
        if type_ == "transcript":
            self._record_transcript(run, event)
            return
        if type_ == "call_status":
            with session_scope(self.engine) as session:
                call = session.get(Call, call_id)
                if call is not None:
                    call.status = event["status"]
                    if event["status"] == "done":
                        call.ended_at = datetime.now(UTC)
        elif type_ == "call_result":
            with session_scope(self.engine) as session:
                call = session.get(Call, call_id)
                if call is not None:
                    call.result_json = json.dumps({k: event[k] for k in ("price", "slot", "insured", "slotOk") if k in event})
        self._emit(run, type_, event, "contact")

    def _record_transcript(self, run: Run, line: dict) -> None:
        """One line of a mock or simulator call goes through `llm_proxy.record_turn`: the Turn row and the `transcript`
        event are written together, keyed by (call_id, seq), so a replayed or retried line is a no-op (T8, invariant 7).

        `seq` comes from the adapter when it numbers its lines (the simulator does); a line without one gets the next
        number for its call, which is stable within the run. `simulated` is kept on the event exactly as the adapter
        sent it, so a judge sees the same label on the transcript as on the call card."""
        call_id = line["call_id"]
        seq = line.get("seq")
        if seq is None:
            seq = run.transcript_seq.get(call_id, 0) + 1
        run.transcript_seq[call_id] = max(int(seq), run.transcript_seq.get(call_id, 0))
        spec = run.proxy_specs.get(call_id)
        if spec is None:
            spec = run.proxy_specs[call_id] = llm_proxy.load_spec(self.engine, call_id)
        llm_proxy.record_turn(self.engine, self.bus, spec, int(seq), line["speaker"], line["text"], simulated=bool(line.get("simulated")))

    async def _ranking(self, run: Run) -> None:
        self._set_status(run, "ranking")
        intake = run.intake
        result = hard_rules(run.offers, run.windows, intake.budget_max, intake.insurance_carrier)
        if not result.ok:
            failure = no_eligible_offer(result)
            raise PipelineFailure(failure["code"], failure["message"])
        priority = "the earliest appointment inside the free windows, then the lowest price"
        try:
            decision, _ = await asyncio.to_thread(
                timed_rank, result.eligible, run.windows, priority, client=self.deps.rank_client(), all_offers=run.offers, carrier=intake.insurance_carrier
            )
        except Exception as exc:
            raise PipelineFailure("RANKING_FAILED", f"Ranking did not produce a decision: {exc}") from exc
        run.winner = next(o for o in run.offers if o.call_id == decision["winner_call_id"])
        with session_scope(self.engine) as session:
            session.get(Task, run.task_id).decision_json = json.dumps(decision)
        self._emit(run, "decision", {"winner": decision["winner_call_id"], "title": f"Why Nemotron picked {run.winner.clinic}",
                                     "reasons": decision["reasons"], "second": decision["second"], "tradeoff": decision["tradeoff"]}, "contact")

    async def _await_approval(self, run: Run) -> bool:
        """Step 6: the one user gate. SMS the pick, wait; after approval_timeout_s send one reminder, then wait as long as it takes (T6)."""
        self._set_status(run, "awaiting_approval")
        winner = run.winner
        expires = self._now(run) + timedelta(seconds=self.approval_timeout_s)
        self._emit(run, "approval_required", {"pick": {"clinic": winner.clinic, "slot": slot_label(winner.slot_start), "price": money(winner.price)},
                                              "expires_at": expires.isoformat()}, "contact")
        self._sms(run, run.owner.phone_e164, texts.approval_sms(winner.clinic, winner.slot_start, winner.price), "approval")
        if not await self._wait(run.task_id, timeout=self.approval_timeout_s):
            self._sms(run, run.owner.phone_e164, texts.approval_reminder_sms(winner.clinic, winner.slot_start, winner.price), "approval_reminder")
            self._emit(run, "task_updated", {"status": "awaiting_approval", "reason": "APPROVAL_TIMEOUT",
                                             "message": "No answer yet; one reminder was sent. Still waiting for Approve or YES."}, "owner")
            await self._wait(run.task_id)
        return self._status(run) == "awaiting_approval"  # a rejection moved it to cancelled

    def _booking(self, run: Run) -> None:
        self._set_status(run, "booking")
        winner = run.winner
        spec = run.specs[winner.call_id]
        slot = {"slot_start": winner.slot_start.isoformat(), "slot_end": winner.slot_end.isoformat()}
        confirmed, _ = receipts.once(
            self.engine, run.task_id, "booking:confirm", "booking",
            lambda: self.deps.voice.confirm_booking(spec, slot),
            external_id=lambda c: c.confirmation_ref,
        )
        confirmation = Confirmation.model_validate(confirmed)
        if confirmation.status == "rejected":
            raise PipelineFailure("BOOKING_REJECTED", f"{winner.clinic} did not confirm the appointment: {confirmation.evidence}")
        address = spec.clinic.address
        booking_fields = {"clinic": winner.clinic, "slot_start": winner.slot_start, "slot_end": winner.slot_end, "price": money(winner.price),
                          "status": confirmation.status, "confirmation_ref": confirmation.confirmation_ref}
        if "address" in Booking.model_fields:  # the calendar adapter (#28) reads the clinic address from the Booking once its type carries it
            booking_fields["address"] = address
        run.booking = Booking(**booking_fields)
        if confirmation.status == "confirmed":
            stored, _ = receipts.once(  # once per task: a retry finds the receipt and never inserts a second event
                self.engine, run.task_id, "calendar", "calendar",
                lambda: self.deps.create_event(run.owner.id, run.booking, f"{run.task_id}:calendar"),
                external_id=lambda r: r.event_id,
            )
            receipt = CalendarReceipt.model_validate(stored)
            run.booking = run.booking.model_copy(update={"calendar_event_id": receipt.event_id})
            payload = {"calendar": texts.calendar_card(winner.slot_start, winner.slot_end, address),
                       "sms_user": texts.booked_sms(winner.clinic, winner.slot_start, winner.price, run.intake.insurance_carrier), "simulated": receipt.simulated}
        else:
            payload = {"calendar": "", "sms_user": texts.tentative_sms(winner.clinic, winner.slot_start), "tentative": True, "simulated": confirmation.simulated}
        with session_scope(self.engine) as session:
            session.get(Task, run.task_id).booking_json = json.dumps(booking_record(run.booking))
        receipt = self._sms(run, run.owner.phone_e164, payload["sms_user"], "booked")
        payload["sms_user"] = receipt.text if receipt else ""  # only a text the adapter accepted is shown as sent
        self._emit(run, "booked", payload, "contact")

    def _transport(self, run: Run) -> bool:
        """Step 8. Returns True when the contact must be asked for a ride."""
        self._set_status(run, "transport")
        self._emit(run, "transport_check", {"status": "checking", "reason": "", "simulated": True}, "contact")
        options = self.deps.transport_check(run.booking, {"needs_ride": run.intake.needs_ride})
        with session_scope(self.engine) as session:
            session.get(Task, run.task_id).transport_json = options.model_dump_json()
        payload = options.dashboard_event()
        payload.pop("type")
        self._emit(run, "transport_check", payload, "contact")
        return run.intake.needs_ride and not options.available

    async def _await_contact(self, run: Run) -> bool:
        self._set_status(run, "awaiting_contact")
        with Session(self.engine) as session:
            contacts = ensure_contacts(session, run.owner.id)
            contact = next((c for c in contacts if c.scope == "ride_requests"), None)
            if contact is None:
                raise PipelineFailure("CONTACT_DECLINED", "No emergency contact is on file to ask for a ride.")
            name, phone = contact.name, contact.phone_e164
        spec = run.specs[run.winner.call_id]
        message = texts.contact_request_message(run.owner.name.split()[0], run.intake.care_type, run.winner.clinic, run.winner.slot_start, spec.clinic.address)
        self._sms(run, phone, message, "contact_request")
        self._emit(run, "contact_request", {"contact": name.split()[0], "message": message}, "contact")
        await self._wait(run.task_id)
        return self._status(run) == "awaiting_contact"

    def _completed(self, run: Run) -> None:
        winner, first = run.winner, run.owner.name.split()[0]
        spec = run.specs[winner.call_id]
        with Session(self.engine) as session:
            contacts = ensure_contacts(session, run.owner.id)
            contact = next((c for c in contacts if c.scope == "ride_requests"), None)
            driver = contact.name.split()[0] if contact else None
            contact_phone = contact.phone_e164 if contact else None
        if run.intake.needs_ride:
            sms_user = texts.ride_confirmed_sms_user(driver or "Your contact", winner.clinic, winner.slot_start)
            sms_contact = texts.ride_confirmed_sms_contact(first, winner.clinic, winner.slot_start)
        else:
            sms_user = texts.booked_sms(winner.clinic, winner.slot_start, winner.price, run.intake.insurance_carrier)
            sms_contact = texts.no_ride_needed_sms_contact(first, winner.clinic, winner.slot_start, spec.clinic.address)
        owner_receipt = self._sms(run, run.owner.phone_e164, sms_user, "final_owner")
        contact_receipt = self._sms(run, contact_phone, sms_contact, "final_contact") if contact_phone else None
        self._emit(run, "notified", {
            "sms_contact": contact_receipt.text if contact_receipt else "",
            "sms_user": owner_receipt.text if owner_receipt else "",
            "simulated": bool((owner_receipt and owner_receipt.simulated) or (contact_receipt and contact_receipt.simulated)),
        }, "contact")
        self._set_status(run, "completed")

    # ---- plumbing -------------------------------------------------------------------------------------------------

    async def _wait(self, task_id: str, timeout: float | None = None) -> bool:
        """Block until a POST or SMS releases this task. With a timeout, return False when nothing came in time and keep
        the wait registered so the answer can still arrive; True means the wait was released and is now closed."""
        event = self._waits.setdefault(task_id, asyncio.Event())
        if timeout is None:
            await event.wait()
        else:
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except TimeoutError:
                if not event.is_set():
                    return False
        self._waits.pop(task_id, None)
        self._claimed.discard(task_id)
        return True

    def _set_status(self, run: Run, status: str) -> None:
        with session_scope(self.engine) as session:
            task = session.get(Task, run.task_id)
            if task.status != status:  # a new task is created in `intake`; every later step is a real transition
                transition(task, status)
        self._emit(run, "task_updated", {"status": status}, "contact")

    def _status(self, run: Run) -> str:
        with Session(self.engine) as session:
            return session.get(Task, run.task_id).status

    def _fail(self, run: Run, code: str, message: str) -> None:
        log.warning("task %s failed: %s", run.task_id, code)
        with session_scope(self.engine) as session:
            task = session.get(Task, run.task_id)
            if task.status not in ("failed", "cancelled", "completed"):
                transition(task, "failed")
        self._emit(run, "task_updated", {"status": "failed", "reason": code, "message": message}, "contact")

    def _emit(self, run: Run, type_: str, payload: dict, visibility: str) -> None:
        emit(self.engine, self.bus, run.task_id, type_, payload, visibility)

    def _sms(self, run: Run, to: str, text: str, step: str):
        """Send one text, keyed by task and step: the receipts table makes a repeat of the step return the first receipt (#24).

        Returns the MessageReceipt, or None when the adapter refused: that is reported to the owner as a
        `task_updated` with reason `SMS_NOT_SENT`, and the text is never shown as sent (status from receipts).
        """
        try:
            stored, _ = receipts.once(  # one text per (task, step); a repeat of the step returns the first receipt
                self.engine, run.task_id, f"sms:{step}", "sms",
                lambda: self.deps.sms_send(to, text, f"{run.task_id}:{step}"),
                external_id=lambda r: r.message_id,
            )
            return MessageReceipt.model_validate(stored)
        except (RuntimeError, OSError, ValueError) as exc:  # the adapters raise plain, readable errors
            log.warning("sms %s for task %s not sent: %s", step, run.task_id, exc)
            self._emit(run, "task_updated", {"status": self._status(run), "reason": "SMS_NOT_SENT", "message": f"{step}: {exc}"}, "owner")
            return None

    def _now(self, run: Run) -> datetime:
        return self.deps.now() if self.deps.now else datetime.now(ZoneInfo(run.owner.timezone))
