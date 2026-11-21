"""Concurrent fixture receptionists, with an injected backend-owned event callback.

Use ``async with callbacks(emit_voice_event) as session``; start_call keeps the
adapter signature and returns immediately. Await session.wait_call(handle) for
the structured Offer. A backend shim must persist/emit events; this module never
imports the backend, writes a database, or opens a network connection.
"""

import asyncio
import hashlib
import inspect
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar

from integrations.phone_policy import require_allowlisted
from integrations.receptionist_script import (
    ReplayPlan,
    build_plan,
    script_for,
    slot_matches,
)
from integrations.types import CallHandle, CallSpec, Confirmation, Offer

EventCallback = Callable[[dict], object]
Sleep = Callable[[float], Awaitable[None]]


def _validate_call(call: CallSpec):
    if os.getenv("VOICE_MODE", "mock") != "mock":
        raise RuntimeError("Scripted receptionists require VOICE_MODE=mock")
    require_allowlisted(call.clinic.phone_e164)


class MockVoiceSession:
    """Own replay tasks for one pipeline run; the caller owns persisted state."""

    def __init__(self, on_event: EventCallback, sleep: Sleep = asyncio.sleep):
        if not callable(on_event):
            raise TypeError("A backend-owned event callback is required")
        self.on_event = on_event
        self.sleep = sleep
        self.closed = False
        self._calls: dict[str, tuple[str, CallHandle, asyncio.Task]] = {}

    def start_call(self, call: CallSpec) -> CallHandle:
        _validate_call(call)
        if self.closed:
            raise RuntimeError("Mock voice session is closed")
        identity = call.model_dump_json()
        previous = self._calls.get(call.call_id)
        if previous:
            if previous[0] != identity:
                raise RuntimeError(
                    "Call ID already exists with a different specification"
                )
            return previous[1].model_copy(deep=True)
        plan = build_plan(call)
        loop = asyncio.get_running_loop()
        reference = hashlib.sha256(call.call_id.encode()).hexdigest()[:24]
        handle = CallHandle(
            call_id=call.call_id, external_ref=f"mock-call-{reference}", simulated=True
        )
        task = loop.create_task(self._replay(plan))
        self._calls[call.call_id] = (identity, handle, task)
        return handle.model_copy(deep=True)

    async def _replay(self, plan: ReplayPlan) -> Offer:
        previous_ms = 0
        for at_ms, event in plan.events:
            await self.sleep((at_ms - previous_ms) / 1000)
            previous_ms = at_ms
            outcome = self.on_event(event.copy())
            if inspect.isawaitable(outcome):
                await outcome
        return plan.offer

    async def wait_call(self, handle: CallHandle) -> Offer:
        saved = self._calls.get(handle.call_id)
        if saved is None or saved[1] != handle:
            raise RuntimeError("Unknown mock call handle")
        return await saved[2]

    async def wait_all(self):
        if self._calls:
            await asyncio.gather(*(saved[2] for saved in self._calls.values()))

    async def close(self):
        self.closed = True
        tasks = [saved[2] for saved in self._calls.values()]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


_current: ContextVar[MockVoiceSession | None] = ContextVar(
    "mock_voice_session", default=None
)


@asynccontextmanager
async def callbacks(on_event: EventCallback, *, sleep: Sleep = asyncio.sleep):
    """Bind a callback per async context, finish tasks or cancel them on failure."""
    session = MockVoiceSession(on_event, sleep)
    token = _current.set(session)
    try:
        yield session
        await session.wait_all()
    finally:
        await session.close()
        _current.reset(token)


def start_call(call: CallSpec) -> CallHandle:
    _validate_call(call)
    session = _current.get()
    if session is None:
        raise RuntimeError("Bind backend callbacks before starting mock calls")
    return session.start_call(call)


def confirm_booking(call: CallSpec, slot) -> Confirmation:
    _validate_call(call)
    _, script = script_for(call)
    if not slot_matches(slot, script["result"]):
        raise RuntimeError("Requested slot does not match the synthetic offer")
    reply = script["booking_reply"]
    reference = None
    if reply["status"] == "confirmed":
        identity = f"{call.call_id}:{script['result']['slot_start']}"
        reference = "mock-booking-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return Confirmation(
        status=reply["status"],
        confirmation_ref=reference,
        evidence="Simulated receptionist: " + reply["evidence"],
        simulated=True,
    )
