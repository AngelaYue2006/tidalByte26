"""The pipeline's dependencies in one place: the integrations adapters, the voice seam and the two Nemotron clients.

`Deps` is what the orchestrator calls; `build_deps(settings)` wires the real modules; tests build a `Deps` with
stand-ins. The orchestrator never imports a vendor SDK and never calls an adapter that is not in here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import Settings
from app.nemotron import local_intake, ranker
from integrations import (
    google_calendar,
    google_distance,
    google_places,
    sms_twilio,
    transport_sim,
)
from integrations.types import CallSpec, Confirmation, Offer

OnEvent = Callable[[dict], Any]


class VoiceAdapter(Protocol):
    """One run of the parallel clinic calls, plus the booking call-back.

    `call_clinics` starts every CallSpec, feeds each `call_status`, `transcript` and `call_result` payload to
    `on_event` as it happens, and returns the structured Offer per call. The receptionist simulator (#13) and the
    ElevenLabs adapter (#26) both fit behind it.
    """

    def call_clinics(self, specs: list[CallSpec], on_event: OnEvent) -> Awaitable[list[Offer]]: ...

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation: ...


class VoiceMockBridge:
    """Adapts integrations.voice_mock (#13) to VoiceAdapter once it has merged; until then it says so plainly."""

    async def call_clinics(self, specs: list[CallSpec], on_event: OnEvent) -> list[Offer]:
        from integrations import voice_mock

        if not hasattr(voice_mock, "callbacks"):
            raise RuntimeError("VOICE_MODE=mock needs the receptionist simulator from integrations/voice_mock.py (#13)")
        async with voice_mock.callbacks(on_event) as session:
            handles = [session.start_call(spec) for spec in specs]
            return [await session.wait_call(handle) for handle in handles]

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        from integrations import voice_mock

        if not hasattr(voice_mock, "confirm_booking"):
            raise RuntimeError("VOICE_MODE=mock needs the receptionist simulator from integrations/voice_mock.py (#13)")
        return voice_mock.confirm_booking(spec, slot)


@dataclass
class Deps:
    free_windows: Callable = google_calendar.free_windows
    create_event: Callable = google_calendar.create_event
    find_clinics: Callable = google_places.find_clinics
    drive: Callable = google_distance.drive
    sms_send: Callable = sms_twilio.send
    transport_check: Callable = transport_sim.check
    voice: VoiceAdapter = field(default_factory=VoiceMockBridge)
    # Nemotron. Built lazily so an all-mock app starts without keys and fails only the step that needs them.
    intake_model: Callable[[], local_intake.IntakeModel] = local_intake.from_env
    rank_client: Callable[[], ranker.ChatJSON] = lambda: _missing("NVIDIA_API_KEY and NEMOTRON_SUPER_ID")
    now: Callable | None = None  # tests pin the clock


def _missing(what: str):
    raise RuntimeError(f"ranking needs {what} in .env")


def build_deps(settings: Settings) -> Deps:
    deps = Deps()
    if settings.voice_mode != "mock":
        raise RuntimeError("VOICE_MODE=live is #26's work; this pipeline runs with VOICE_MODE=mock")

    def rank_client() -> ranker.ChatJSON:
        return ranker.NvidiaChatClient(settings.nvidia_api_key or "", settings.require_model("super"))

    deps.rank_client = rank_client
    return deps
