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
from app.voice_replay import FixtureReplay
from integrations import (
    google_calendar,
    google_distance,
    google_places,
    sms_twilio,
    transport_sim,
)
from integrations.types import CallHandle, CallSpec, Confirmation, Offer

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
    """The default voice path for VOICE_MODE=mock.

    Uses integrations.voice_mock (#13) when that module has merged, else the backend's own FixtureReplay of the same
    receptionists.json. Either way every event is simulated and nothing is dialled. `sleep` lets tests run the
    fixture timing instantly; the app uses the real clock.
    """

    live = False

    def __init__(self, sleep=None) -> None:
        self._sleep = sleep
        self._replay: FixtureReplay | None = None

    def _simulator(self):
        from integrations import voice_mock

        return voice_mock if hasattr(voice_mock, "callbacks") and hasattr(voice_mock, "confirm_booking") else None

    def _fallback(self) -> FixtureReplay:
        if self._replay is None:
            self._replay = FixtureReplay(self._sleep) if self._sleep else FixtureReplay()
        return self._replay

    async def call_clinics(self, specs: list[CallSpec], on_event: OnEvent) -> list[Offer]:
        simulator = self._simulator()
        if simulator is None:
            return await self._fallback().call_clinics(specs, on_event)
        kwargs = {"sleep": self._sleep} if self._sleep else {}
        async with simulator.callbacks(on_event, **kwargs) as session:
            handles = [session.start_call(spec) for spec in specs]
            return [await session.wait_call(handle) for handle in handles]

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        simulator = self._simulator()
        if simulator is None:
            return self._fallback().confirm_booking(spec, slot)
        return simulator.confirm_booking(spec, slot)


class VoiceLiveBridge:
    """VOICE_MODE=live: ElevenLabs `start_call`; booking confirm stays on the mock path (`simulated: true`).

    The orchestrator starts each call and waits for post-call webhooks; `call_clinics` is not used in live mode.
    """

    live = True

    def __init__(
        self,
        start_call: Callable[[CallSpec], CallHandle],
        confirm_booking: Callable[[CallSpec, dict], Confirmation],
    ) -> None:
        self._start_call = start_call
        self._confirm_booking = confirm_booking

    def start_call(self, spec: CallSpec) -> CallHandle:
        return self._start_call(spec)

    async def call_clinics(self, specs: list[CallSpec], on_event: OnEvent) -> list[Offer]:
        raise RuntimeError(
            "VOICE_MODE=live: the orchestrator starts calls and waits for post-call results"
        )

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        return self._confirm_booking(spec, slot)


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
    call_result_timeout_s: float = 180.0


def _missing(what: str):
    raise RuntimeError(f"ranking needs {what} in .env")


def build_deps(settings: Settings) -> Deps:
    deps = Deps()
    deps.call_result_timeout_s = float(getattr(settings, "call_result_timeout_s", 180.0) or 180.0)

    if settings.voice_mode == "live":
        # Fail closed at startup with readable names (same set as LIVE_REQUIREMENTS["voice"] plus Twilio number).
        settings.require(
            "NVIDIA_API_KEY",
            "NEMOTRON_LIGHTNING_ID",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_AGENT_ID",
            "ELEVENLABS_PHONE_NUMBER_ID",
            "ELEVENLABS_WEBHOOK_SECRET",
            "LLM_PROXY_SECRET",
            "PUBLIC_BASE_URL",
            "DEMO_PHONE_ALLOWLIST",
            "TWILIO_PHONE_NUMBER",
        )
        from integrations import voice_elevenlabs

        # Booking confirm stays on the fixture/mock path (simulated); live confirm_booking is unwired.
        replay = FixtureReplay()
        deps.voice = VoiceLiveBridge(
            start_call=voice_elevenlabs.start_call,
            confirm_booking=replay.confirm_booking,
        )
    elif settings.voice_mode != "mock":
        raise RuntimeError(f"VOICE_MODE must be mock or live, got {settings.voice_mode!r}")

    def rank_client() -> ranker.ChatJSON:
        return ranker.NvidiaChatClient(settings.nvidia_api_key or "", settings.require_model("super"))

    deps.rank_client = rank_client
    return deps
