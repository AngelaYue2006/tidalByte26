#!/usr/bin/env python3
"""Seed one call record and place one real ElevenLabs call, so the judges hear the agent while the pipeline runs on mock (D17).

    python scripts/demo_call.py --dry-run            # seed the Task + Call only; print the masked request, dial nothing
    python scripts/demo_call.py                      # seed, then ring DEMO_PHONE_ALLOWLIST entry 1 (the first number)
    python scripts/demo_call.py --to-entry 2         # ring the second allowlisted number instead

Run from the repo root with the backend up on PUBLIC_BASE_URL (it answers the agent's custom-LLM turns and the post-call
webhook) and the root .env filled in. The Task + Call rows go into the backend's own SQLite file, so the proxy's
`load_spec` finds the call and the transcript lands on the dashboard's History for that task. Prints the call_id and the
ElevenLabs conversation id and nothing else: no key, no secret, no phone number. The request shape is docs/ELEVENLABS.md,
"Outbound call"; `custom_llm_extra_body` carries `call_id` and `LLM_PROXY_SECRET` exactly as `routers/llm_proxy.py` reads them.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.config import Settings, load_settings
from app.models import Call, Task
from app.nemotron.types import IntakeRequest, TimeRange
from sqlmodel import Session, create_engine

OUTBOUND_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
CLINIC = "Bright Smile Dental"
NEEDED = ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID", "LLM_PROXY_SECRET", "PUBLIC_BASE_URL", "DEMO_PHONE_ALLOWLIST")


class Refused(Exception):
    """A reason not to dial, in words a person can read. Never carries a number or a secret."""


@dataclass(frozen=True)
class Seeded:
    task_id: str
    call_id: str


def database_url(settings: Settings) -> str:
    """The backend's own database. A relative sqlite path in .env is relative to backend/, where uvicorn runs."""
    url = settings.database_url
    prefix = "sqlite:///"
    if url.startswith("sqlite:////"):
        return url
    if url.startswith(prefix):
        relative = url[len(prefix):].removeprefix("./")
        if relative == ":memory:" or Path(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
            return url
        return f"sqlite:///{(ROOT / 'backend' / relative).resolve().as_posix()}"
    return url


def target_number(settings: Settings, entry: int) -> str:
    """Allowlist entry `entry` (1-based). The fixture people's fictional numbers and anything off the list are refused."""
    allowlist = list(settings.demo_phone_allowlist)
    if not 1 <= entry <= len(allowlist):
        raise Refused(f"--to-entry must be between 1 and {len(allowlist)} (the DEMO_PHONE_ALLOWLIST entries)")
    number = allowlist[entry - 1]
    if number.startswith("+1555555") or not number.startswith("+"):  # backend/fixtures/users.json uses the fictional 555-555-01xx range
        raise Refused(f"allowlist entry {entry} is a fixture number, not a phone that rings")
    return number


def demo_windows(now: datetime) -> list[dict]:
    """Two free windows in the current week in the owner's timezone: Tuesday 9:00-12:00 and Thursday 13:00-17:00,
    so an offer of "Thursday at two" fits and "Thursday at 9:30" does not."""
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    tuesday, thursday = monday + timedelta(days=1), monday + timedelta(days=3)
    return [
        {"start": tuesday.replace(hour=9).isoformat(), "end": tuesday.replace(hour=12).isoformat()},
        {"start": thursday.replace(hour=13).isoformat(), "end": thursday.replace(hour=17).isoformat()},
    ]


def seed(engine, clinic_phone: str, *, now: datetime | None = None, owner_id: str = "mary") -> Seeded:
    """One Task in `calling` with the redacted dental intake, one Call in `dialing` with no result."""
    tz = ZoneInfo("America/Chicago")
    now = now or datetime.now(tz)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    intake = IntakeRequest(
        care_type="dental cleaning", budget_max=150, insurance_carrier="Delta Dental",
        time_range=TimeRange(start=monday.isoformat(), end=(monday + timedelta(days=6, hours=23, minutes=59)).isoformat()),
        needs_ride=True, search_area="near home", dropped_fields=["mobility_details"],
    )
    task_id = uuid.uuid4().hex
    call_id = f"{task_id[:8]}-A"
    with Session(engine) as session:
        session.add(Task(id=task_id, owner_id=owner_id, status="calling", intake_json=intake.model_dump_json(), windows_json=json.dumps(demo_windows(now))))
        session.add(Call(id=call_id, task_id=task_id, clinic_name=CLINIC, clinic_phone=clinic_phone, distance_mi=1.2, status="dialing", started_at=now))
        session.commit()
    return Seeded(task_id=task_id, call_id=call_id)


def outbound_body(settings: Settings, call_id: str, to_number: str) -> dict:
    return {
        "agent_id": settings.elevenlabs_agent_id,
        "agent_phone_number_id": settings.elevenlabs_phone_number_id,
        "to_number": to_number,
        "conversation_initiation_client_data": {
            "custom_llm_extra_body": {"call_id": call_id, "proxy_secret": settings.llm_proxy_secret},
            "dynamic_variables": {"call_id": call_id},
        },
        "call_recording_enabled": False,
    }


def masked(body: dict) -> dict:
    """The request as it may be printed: ids shortened, the secret and the number hidden."""
    shown = json.loads(json.dumps(body))
    shown["to_number"] = "+…" + body["to_number"][-2:]
    shown["agent_id"] = (body["agent_id"] or "")[:4] + "…"
    shown["agent_phone_number_id"] = (body["agent_phone_number_id"] or "")[:4] + "…"
    shown["conversation_initiation_client_data"]["custom_llm_extra_body"]["proxy_secret"] = "<LLM_PROXY_SECRET>"
    return shown


def place_call(settings: Settings, body: dict) -> str:
    """POST the outbound call; return the conversation id. Raises Refused with the HTTP status on anything else."""
    import httpx

    response = httpx.post(OUTBOUND_CALL_URL, headers={"xi-api-key": settings.elevenlabs_api_key or "", "content-type": "application/json"}, json=body, timeout=30)
    try:
        data = response.json()
    except ValueError:
        data = {}
    conversation_id = data.get("conversation_id")
    if response.status_code >= 300 or data.get("success") is not True or not isinstance(conversation_id, str):
        raise Refused(f"ElevenLabs did not accept the call: HTTP {response.status_code}, message {str(data.get('message') or data.get('detail') or '')[:120]!r}")
    return conversation_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to-entry", type=int, default=1, help="1-based DEMO_PHONE_ALLOWLIST entry to ring (default 1)")
    parser.add_argument("--dry-run", action="store_true", help="seed the Task and Call, print the masked request, dial nothing")
    args = parser.parse_args(argv)
    settings = load_settings()
    missing = [name for name in NEEDED if not getattr(settings, name.lower())]
    if missing:
        print("refused: empty in .env:", ", ".join(missing))
        return 2
    try:
        to_number = target_number(settings, args.to_entry)
        engine = create_engine(database_url(settings))
        seeded = seed(engine, to_number)
        body = outbound_body(settings, seeded.call_id, to_number)
        print("seeded task", seeded.task_id, "call", seeded.call_id, "to allowlist entry", args.to_entry)
        print("request:", json.dumps(masked(body), indent=2))
        if args.dry_run:
            print("dry run: nothing dialed")
            return 0
        conversation_id = place_call(settings, body)
    except Refused as why:
        print("refused:", why)
        return 1
    with Session(engine) as session:
        call = session.get(Call, seeded.call_id)
        call.external_ref = conversation_id
        session.add(call)
        session.commit()
    print("dialing: call_id", seeded.call_id, "conversation_id", conversation_id)
    print("watch the dashboard History for task", seeded.task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
