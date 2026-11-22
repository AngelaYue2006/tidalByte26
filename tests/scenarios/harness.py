"""The scenario harness: the FastAPI app with every adapter in mock mode, Nano and Super replaced by stand-ins, the clock
pinned to the demo week, and a recording wrapper around every adapter so a test can read what left the pipeline.

Nothing here changes backend behaviour. `ScenarioVoice` replays backend/fixtures/receptionists.json like the app's own
mock path and lets a scenario override one clinic's offer or booking reply (T4, T5, T7) or hold a call open (T11).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.adapters import Deps
from app.config import load_settings
from app.main import create_app
from app.routers.webhooks import sign
from app.voice_replay import FixtureReplay
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from integrations.types import CallSpec, Confirmation, Offer

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "shared"

CHICAGO = ZoneInfo("America/Chicago")
DEMO_NOW = datetime(2026, 11, 23, 9, 0, tzinfo=CHICAGO)  # Monday of the demo week
OWNER, CONTACT = "mary", "sarah"
OWNER_PHONE, CONTACT_PHONE = "+15555550100", "+15555550101"
UNKNOWN_PHONE = "+15555550999"  # not on the allowlist, not in users.json
ALLOWLIST = f"{OWNER_PHONE},{CONTACT_PHONE},+15555550111,+15555550112,+15555550113"
WEBHOOK_SECRET = "scenario-webhook-secret-0123456789abcdef"

BRIGHT, SMILE, OAK = "Bright Smile Dental", "Smile Co.", "Oak Dental"
DEMO_TEXT = "I need a dental cleaning this week, under $150. I have Delta Dental. My knee makes walking hard so I'll need a ride."
DEMO_INTAKE = {
    "care_type": "dental cleaning", "budget_max": 150, "insurance_carrier": "Delta Dental", "time_phrase": "this week",
    "needs_ride": True, "search_area": "near home", "dropped_fields": ["mobility_details"],
}
DEMO_CHIPS = ["Dental cleaning", "Max $150", "Delta Dental", "Free: Tue pm, Thu am", "!Processed on device"]
VOICE_EVENTS = {"call_status", "transcript", "call_result"}

_SCHEMAS = {n: json.loads((SHARED / f"{n}.schema.json").read_text()) for n in ("events", "intake_request", "decision", "task")}
_REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in _SCHEMAS.values()])
EVENTS_VALIDATOR = Draft202012Validator(_SCHEMAS["events"], registry=_REGISTRY, format_checker=FormatChecker())
TASK_VALIDATOR = Draft202012Validator(_SCHEMAS["task"], registry=_REGISTRY, format_checker=FormatChecker())

_keys = itertools.count(1)


def fresh_key(prefix: str) -> str:
    return f"{prefix}-{next(_keys)}"


def validate_event(event: dict) -> None:
    """Validate the flat event as the dashboard receives it (the stream id is not part of the schema)."""
    EVENTS_VALIDATOR.validate({k: v for k, v in event.items() if k != "id"})


# ---- stand-ins for the two Nemotron services ---------------------------------------------------------------------


class FakeNano:
    """Nano on the device: answers the intake prompt with a fixed proposal (the deterministic backstop still runs) and
    the contact-message prompt (#23) with a scoped message built from the appointment facts in the record it is given."""

    name = "fake-nano"

    def __init__(self, proposal: dict | None = None) -> None:
        self.proposal = dict(proposal or DEMO_INTAKE)
        self.utterances: list[str] = []  # the raw requests the intake prompt received
        self.contact_records: list[dict] = []  # the full records the contact prompt received, both on the device only

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        if "message" in schema.get("properties", {}):
            record = json.loads(user)
            self.contact_records.append(record)
            a = record["appointment"]
            return {"message": (f"Hi {record['contact']['first_name']}, {a['owner_first_name']} has a {a['for']} at {a['clinic']} on {a['when']}, "
                                f"{a['address']}. No accessible ride was found. Can you drive? Reply YES or NO.")}
        self.utterances.append(user)
        return dict(self.proposal)


class RecordingSuper:
    """Super in the cloud: records every prompt it is sent and picks the cheapest offer, earliest slot on a tie."""

    model_id = "fake-super"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def offers_seen(self) -> list[list[str]]:
        """call_ids offered to the ranker, one list per ranking prompt."""
        seen = []
        for prompt in self.prompts:
            try:
                seen.append([o["call_id"] for o in json.loads(prompt).get("offers", [])])
            except ValueError:
                continue
        return seen

    def complete_json(self, system: str, user: str, *, previous=None) -> str:
        self.prompts.append(user)
        offers = json.loads(user).get("offers", [])
        ranked = sorted(offers, key=lambda o: (float(o["price"].lstrip("$").replace(",", "")), o["slot_start"]))
        runner = ranked[1]["clinic"] if len(ranked) > 1 else "no other clinic"
        return json.dumps({
            "winner_call_id": ranked[0]["call_id"],
            "ranked": [{"call_id": o["call_id"], "score": 95 - 10 * i} for i, o in enumerate(ranked)],
            "tradeoff": f"{runner} was the alternative, but {ranked[0]['clinic']} costs less and fits your free time.",
        })


# ---- the voice seam -----------------------------------------------------------------------------------------------


async def instant(_seconds: float) -> None:
    """Stands in for asyncio.sleep: fixture timing is honoured in order, not in wall-clock."""


class Gate:
    """Holds one clinic's call open after `after_lines` transcript lines until the test releases it (T11)."""

    def __init__(self, clinic: str, after_lines: int) -> None:
        self.clinic, self.after_lines = clinic, after_lines
        self.reached = threading.Event()  # the call is paused
        self.released = threading.Event()  # the test lets it continue
        self._lines = 0

    def wants_hold(self, clinic: str, payload: dict) -> bool:
        if clinic != self.clinic or payload.get("type") != "transcript" or self.reached.is_set():
            return False
        self._lines += 1
        return self._lines == self.after_lines

    async def hold(self) -> None:
        self.reached.set()
        while not self.released.is_set():
            await asyncio.sleep(0.01)


@dataclass
class ScenarioVoice(FixtureReplay):
    """The fixture receptionists with per-clinic overrides. Emits the same simulated events as the app's mock path."""

    offer_overrides: dict[str, dict] = field(default_factory=dict)  # clinic name -> Offer fields to replace
    booking_replies: dict[str, str] = field(default_factory=dict)  # clinic name -> confirmed | tentative | rejected
    gate: Gate | None = None
    confirmed: list[str] = field(default_factory=list)  # call ids whose booking call-back ran
    specs: list[CallSpec] = field(default_factory=list)  # every CallSpec handed to the voice adapter

    def __post_init__(self) -> None:
        FixtureReplay.__init__(self, instant)

    def offer_for(self, spec: CallSpec) -> Offer:
        offer = super().offer_for(spec)
        override = self.offer_overrides.get(spec.clinic.name)
        return offer.model_copy(update=override) if override else offer

    async def call_clinics(self, specs, on_event):
        self.specs.extend(specs)
        return await super().call_clinics(specs, on_event)

    async def _replay(self, spec: CallSpec, on_event) -> Offer:
        for _at_ms, payload in self.timeline(spec):
            on_event(payload)
            if self.gate and self.gate.wants_hold(spec.clinic.name, payload):
                await self.gate.hold()
        return self.offer_for(spec)

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        self.confirmed.append(spec.call_id)
        offer = self.offer_for(spec)
        if slot.get("slot_start") != offer.slot_start.isoformat():
            raise RuntimeError("requested slot does not match the offer the receptionist made")
        _, script = self._script(spec)
        status = self.booking_replies.get(spec.clinic.name, script["booking_reply"]["status"])
        ref = f"mock-booking-{spec.call_id}" if status == "confirmed" else None
        return Confirmation(status=status, confirmation_ref=ref, evidence=f"Simulated receptionist: {status}", simulated=True)


# ---- the lab ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outbound:
    """One call into an adapter or cloud model: the only ways anything leaves the pipeline."""

    target: str
    payload: str  # the arguments, serialised

    @property
    def to_cloud(self) -> bool:
        return self.target in CLOUD_TARGETS


CLOUD_TARGETS = frozenset({"find_clinics", "drive", "rank", "voice.call_clinics"})


class Lab:
    """One app under test plus everything a scenario needs to drive and inspect it."""

    def __init__(self, client: TestClient, voice: ScenarioVoice, nano: FakeNano, ranker: RecordingSuper, metrics_path: Path) -> None:
        self.client, self.voice, self.nano, self.ranker, self.metrics_path = client, voice, nano, ranker, metrics_path
        self.outbound: list[Outbound] = []
        self.sms: list[tuple[str, str, str]] = []  # (to, text, idempotency_key)
        self.calendar_writes: list[str] = []  # idempotency keys of create_event calls

    @property
    def app(self):
        return self.client.app

    def close(self) -> None:
        self.client.__exit__(None, None, None)

    # -- REST -------------------------------------------------------------------------------------------------------

    def start(self, text: str = DEMO_TEXT, key: str | None = None, owner: str = OWNER, actor: str | None = None) -> str:
        r = self.client.post(
            f"/api/requests?viewer_id={actor or owner}",
            json={"owner_id": owner, "actor_id": actor or owner, "text": text, "idempotency_key": key or fresh_key("req")},
        )
        assert r.status_code == 201, r.text
        return r.json()["task_id"]

    def approve(self, task_id: str, decision: str = "approve", key: str | None = None, actor: str = OWNER):
        return self.client.post(
            f"/api/tasks/{task_id}/approve?viewer_id={actor}",
            json={"actor_id": actor, "decision": decision, "idempotency_key": key or fresh_key("approve")},
        )

    def offer(self, task_id: str, can_drive: bool, key: str | None = None, pickup_time: str | None = None, contact: str = CONTACT):
        return self.client.post(
            f"/api/contacts/offers?viewer_id={contact}",
            json={"task_id": task_id, "contact_id": contact, "offer": {"can_drive": can_drive, "pickup_time": pickup_time}, "idempotency_key": key or fresh_key("offer")},
        )

    def task(self, task_id: str, viewer: str = OWNER) -> dict:
        r = self.client.get(f"/api/tasks/{task_id}?viewer_id={viewer}")
        assert r.status_code == 200, r.text
        return r.json()

    def events(self, task_id: str, viewer: str = OWNER) -> list[dict]:
        r = self.client.get(f"/api/tasks/{task_id}/events?viewer_id={viewer}")
        assert r.status_code == 200, r.text
        return r.json()

    def types(self, task_id: str, viewer: str = OWNER, *, without_voice: bool = False) -> list[str]:
        types = [e["type"] for e in self.events(task_id, viewer)]
        return [t for t in types if t not in VOICE_EVENTS] if without_voice else types

    def of_type(self, task_id: str, type_: str, viewer: str = OWNER) -> list[dict]:
        return [e for e in self.events(task_id, viewer) if e["type"] == type_]

    def history(self, viewer: str = OWNER, **params) -> list[dict]:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        r = self.client.get(f"/api/tasks?viewer_id={viewer}" + (f"&{query}" if query else ""))
        assert r.status_code == 200, r.text
        return r.json()

    def call_ids(self, task_id: str) -> dict[str, str]:
        """clinic name -> the task-unique call id, from the call_start events."""
        return {e["clinic"]: e["call_id"] for e in self.of_type(task_id, "call_start")}

    def twilio_sms(self, sender: str, body: str, message_sid: str, **extra):
        """An inbound SMS as the form Twilio posts (docs/ARCHITECTURE.md, REST interface), handled in SMS_MODE=mock: no
        Twilio signature is attached, so these tests exercise the allowlist, matching and replay rules, not the live
        signature check (integrations/tests covers that). The ElevenLabs post-call replay below is signed."""
        form = {"From": sender, "To": "+15555550000", "Body": body, "MessageSid": message_sid, **extra}
        return self.client.post("/api/webhooks/twilio/sms", data=form)

    def post_call_webhook(self, payload: dict):
        raw = json.dumps(payload).encode()
        return self.client.post(
            "/api/webhooks/elevenlabs/post-call", content=raw,
            headers={"Content-Type": "application/json", "ElevenLabs-Signature": sign(raw, WEBHOOK_SECRET)},
        )

    def reset(self):
        return self.client.post("/api/demo/reset")

    # -- waiting and streaming --------------------------------------------------------------------------------------

    def wait_for(self, task_id: str, status: str, timeout: float = 5.0) -> dict:
        """Poll the owner projection until the task reaches `status`; fail fast on failed/cancelled."""
        deadline = time.time() + timeout
        task = self.task(task_id)
        while time.time() < deadline:
            task = self.task(task_id)
            if task["status"] == status:
                return task
            if task["status"] in ("failed", "cancelled") and status not in ("failed", "cancelled"):
                last = self.of_type(task_id, "task_updated")[-1]
                raise AssertionError(f"task {task['status']}: {task.get('failure_reason')} {last}")
            time.sleep(0.02)
        raise AssertionError(f"task never reached {status}; last status {task['status']}")

    def settle(self, seconds: float = 0.3) -> None:
        """Give the server loop time to do anything it was going to do, so a 'nothing happened' assertion means something."""
        time.sleep(seconds)

    @contextmanager
    def stream(self, viewer: str = OWNER) -> Iterator[Iterator[tuple[int | None, dict]]]:
        """GET /api/live as the dashboard does: yields (id, message) pairs, the snapshot first."""
        with self.client.stream("GET", f"/api/live?viewer_id={viewer}") as resp:
            assert resp.status_code == 200
            yield sse_messages(resp.iter_lines())

    def snapshot(self, viewer: str = OWNER) -> tuple[int | None, dict]:
        with self.stream(viewer) as messages:
            return next(messages)

    # -- the trail --------------------------------------------------------------------------------------------------

    def validate_trail(self, task_id: str) -> None:
        """Every event in both views and both task projections match the shared schemas."""
        for viewer in (OWNER, CONTACT):
            for event in self.events(task_id, viewer):
                validate_event(event)
            TASK_VALIDATOR.validate(self.task(task_id, viewer))

    def sms_to(self, phone: str) -> list[str]:
        return [text for to, text, _ in self.sms if to == phone]

    def metrics_rows(self) -> list[dict]:
        if not self.metrics_path.exists():
            return []
        return [json.loads(line) for line in self.metrics_path.read_text().splitlines() if line.strip()]


def sse_messages(lines: Iterator[str]) -> Iterator[tuple[int | None, dict]]:
    event_id, data = None, None
    for line in lines:
        if line == "":
            if data is not None:
                yield (int(event_id) if event_id else None), json.loads(data)
            event_id, data = None, None
        elif line.startswith("id: "):
            event_id = line[4:]
        elif line.startswith("data: "):
            data = line[6:]


def until(messages, predicate, limit: int = 400) -> tuple[int | None, dict]:
    for _ in range(limit):
        message = next(messages)
        if predicate(message):
            return message
    raise AssertionError("message not seen on the stream")


def make_lab(monkeypatch, root: Path, *, voice: ScenarioVoice | None = None, nano: FakeNano | None = None, env: dict | None = None) -> Lab:
    """The app with its default wiring (`Deps()`): only Nano and Super are stand-ins, the clock is pinned, and every
    adapter is wrapped to record what it was given."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", ALLOWLIST)  # the integrations mocks read the allowlist from the environment
    for var in ("VOICE_MODE", "PLACES_MODE", "CALENDAR_MODE", "SMS_MODE", "TRANSPORT_MODE"):
        monkeypatch.delenv(var, raising=False)
    metrics_path = root / "metrics.jsonl"
    monkeypatch.setenv("METRICS_PATH", str(metrics_path))
    environ = {
        "APP_ENV": "development",
        "APP_TIMEZONE": "America/Chicago",
        "DATABASE_URL": f"sqlite:///{root}/lifeline.db",
        "DEMO_PHONE_ALLOWLIST": ALLOWLIST,
        "ELEVENLABS_WEBHOOK_SECRET": WEBHOOK_SECRET,
        **(env or {}),
    }
    settings = load_settings(env_file=None, environ=environ)
    voice = voice or ScenarioVoice()
    nano = nano or FakeNano()
    ranker = RecordingSuper()
    deps = Deps(voice=voice, intake_model=lambda: nano, rank_client=lambda: ranker, now=lambda: DEMO_NOW)
    app = create_app(settings, deps=deps)
    app.state.heartbeat_seconds = 0.2
    client = TestClient(app)
    client.__enter__()
    lab = Lab(client, voice, nano, ranker, metrics_path)
    _wire_recorders(lab, deps)
    assert client.get("/api/session").json() == {"ok": True}  # the dashboard's one-time call; the cookie jar keeps it
    return lab


def _wire_recorders(lab: Lab, deps: Deps) -> None:
    def record(target: str, fn):
        def wrapped(*args, **kwargs):
            lab.outbound.append(Outbound(target, json.dumps([_plain(a) for a in args] + [_plain(kwargs)], default=str, ensure_ascii=False)))
            return fn(*args, **kwargs)

        return wrapped

    def sms_send(to, text, key):
        lab.sms.append((to, text, key))
        return record("sms_send", real_sms)(to, text, key)

    def create_event(owner_id, booking, key):
        lab.calendar_writes.append(key)
        return record("create_event", real_calendar)(owner_id, booking, key)

    real_sms, real_calendar = deps.sms_send, deps.create_event
    deps.sms_send = sms_send
    deps.create_event = create_event
    deps.find_clinics = record("find_clinics", deps.find_clinics)
    deps.drive = record("drive", deps.drive)
    deps.free_windows = record("free_windows", deps.free_windows)
    deps.transport_check = record("transport_check", deps.transport_check)
    real_rank = lab.ranker.complete_json
    lab.ranker.complete_json = record("rank", real_rank)
    real_call = lab.voice.call_clinics

    async def call_clinics(specs, on_event):
        lab.outbound.append(Outbound("voice.call_clinics", json.dumps([s.model_dump(mode="json") for s in specs], ensure_ascii=False)))
        return await real_call(specs, on_event)

    lab.voice.call_clinics = call_clinics


def _plain(value):
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else value
