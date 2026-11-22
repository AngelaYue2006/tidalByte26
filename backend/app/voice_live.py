"""One live discovery call. Backend receipts own state; integrations owns vendor I/O."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import receipts
from app.db import session_scope
from app.models import Call, Receipt, Task
from integrations import voice_elevenlabs
from integrations.phone_policy import require_allowlisted
from integrations.types import CallHandle, CallSpec, Distance, Offer


class VoiceLiveBridge:
    """Dial once, then read the facts committed by the signed post-call webhook.

    A durable claim precedes the outbound request. An ambiguous request is never
    retried automatically. The wait timeout does not hang up a vendor call.
    Webhooks/proxy already persist and publish events; do not replay them here.
    """

    simulated = False
    booking_available = False

    def __init__(self, engine: Engine, *, timeout_s=360, poll_s=0.25):
        self.engine = engine
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    async def call_clinics(self, specs: list[CallSpec], on_event) -> list[Offer]:
        if len(specs) != 1:
            raise RuntimeError("Live voice requires exactly one demo call")
        spec = specs[0]
        require_allowlisted(spec.clinic.phone_e164)
        # Validate durable context and route facts before claiming or dialling.
        with Session(self.engine) as session:
            call = session.get(Call, spec.call_id)
            task = session.get(Task, call.task_id) if call else None
            if (not task or not task.intake_json or not task.windows_json
                    or call.clinic_phone != spec.clinic.phone_e164
                    or call.clinic_name != spec.clinic.name):
                raise RuntimeError("Live call needs matching persisted task and call context")
            task_id = task.id
        route = receipts.find(self.engine, task_id, f"call:route:{spec.call_id}")
        if route is None:
            raise RuntimeError("Live call needs a recorded distance and driving time")
        distance = Distance.model_validate(receipts.payload_of(route))
        if distance.place_id != spec.clinic.place_id:
            raise RuntimeError("Live call route does not match the clinic")
        _, repeated = receipts.record(
            self.engine, task_id, f"voice:start:{spec.call_id}", "voice",
            {"state": "pending"},
        )
        if not repeated:
            # Keep the event loop free for Lightning proxy, webhooks and SSE.
            # Cancellation cannot stop this worker: the durable claim prevents a
            # second dial, and a signed webhook can still bind its conversation.
            handle = await asyncio.to_thread(self._dial, spec)
            self._bind(spec, handle)
        else:
            with Session(self.engine) as session:
                call = session.get(Call, spec.call_id)
                if not call or not call.external_ref:
                    raise RuntimeError("Previous live dial has an unknown outcome; reconcile it before retrying")
        deadline = asyncio.get_running_loop().time() + self.timeout_s
        while True:
            with Session(self.engine) as session:
                call = session.get(Call, spec.call_id)
                if call is None:
                    raise RuntimeError("Live call context was removed")
                if call.status == "done":
                    return self._offers(spec, call, distance)
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("Timed out waiting for verified live call results; call may still be active")
            await asyncio.sleep(self.poll_s)

    @staticmethod
    def _dial(spec):
        try:
            handle = CallHandle.model_validate(voice_elevenlabs.start_call(spec))
            if handle.simulated or handle.call_id != spec.call_id:
                raise ValueError("unexpected call receipt")
            return handle
        except Exception:  # noqa: BLE001 - sanitize credential-bearing vendor errors
            # Vendor exceptions must not leak credentials or request payloads.
            raise RuntimeError("Live call was not verified; check adapter configuration and reconcile before retrying") from None

    def _bind(self, spec, handle):
        with session_scope(self.engine) as session:
            call = session.get(Call, spec.call_id)
            if call is None or (call.external_ref and call.external_ref != handle.external_ref):
                raise RuntimeError("Live conversation receipt does not match the persisted call")
            call.external_ref = handle.external_ref
            receipt = session.exec(select(Receipt).where(
                Receipt.task_id == call.task_id, Receipt.step == f"voice:start:{spec.call_id}",
            )).one()
            receipt.external_id = handle.external_ref
            receipt.payload_json = json.dumps({"state": "accepted", **handle.model_dump()})

    @staticmethod
    def _offers(spec, call, distance):
        facts = json.loads(call.result_json or "{}")
        if (facts.get("source") not in {"data_collection", "super", "mixed"}
                or facts.get("price_usd") is None
                or type(facts.get("insured")) is not bool
                or not facts.get("slot_start") or not facts.get("slot_end")):
            return []
        return [Offer(
            call_id=spec.call_id, clinic=spec.clinic.name, price=facts["price_usd"],
            insured=facts["insured"], slot_start=facts["slot_start"], slot_end=facts["slot_end"],
            distance_mi=distance.miles, drive_min=distance.minutes,
        )]

    def confirm_booking(self, spec, slot):
        raise RuntimeError("Live booking needs a booking-capable agent and structured confirmation receipt")
