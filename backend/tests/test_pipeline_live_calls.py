"""#116: VOICE_MODE=live calling starts real-path calls and waits for post-call results (or timeout)."""

from __future__ import annotations

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.adapters import Deps
from app.config import load_settings
from app.main import create_app
from app.models import Call
from app.routers.webhooks import sign
from app.voice_replay import FixtureReplay
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from integrations.types import CallHandle, CallSpec, Confirmation
from tests.stand_ins import DEMO_TEXT, FakeNano, FakeSuper

DEMO_NOW = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
FAKE_PHONES = "+15555550100,+15555550101,+15555550111,+15555550112,+15555550113"
WEBHOOK_SECRET = "live-pipeline-webhook-secret-0123456789abcdef"

COLLECTIONS = {
    "Bright Smile Dental": {"price": {"value": "$95", "rationale": "said"}, "slot": "Thu 9:30", "insured": "yes"},
    "Smile Co.": {"price": {"value": "$120", "rationale": "said"}, "slot": "Fri 4:00", "insured": "yes"},
    "Oak Dental": {"price": {"value": "$140", "rationale": "said"}, "slot": "next Monday 10:00", "insured": "yes"},
}


class FakeLiveVoice:
    """Records start_call; booking stays on FixtureReplay (simulated)."""

    live = True

    def __init__(self) -> None:
        self.starts: list[CallSpec] = []
        self._confirm = FixtureReplay().confirm_booking

    def start_call(self, spec: CallSpec) -> CallHandle:
        self.starts.append(spec)
        return CallHandle(call_id=spec.call_id, external_ref=f"conv-{spec.call_id}", simulated=False)

    async def call_clinics(self, specs, on_event):
        raise RuntimeError("live path must not call call_clinics")

    def confirm_booking(self, spec: CallSpec, slot: dict) -> Confirmation:
        return self._confirm(spec, slot)


def make_live_client(monkeypatch, tmp_path, *, timeout_s: float = 180.0):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)
    for var in ("VOICE_MODE", "PLACES_MODE", "CALENDAR_MODE", "SMS_MODE", "TRANSPORT_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    environ = {
        "DATABASE_URL": f"sqlite:///{tmp_path}/lifeline.db",
        "DEMO_PHONE_ALLOWLIST": FAKE_PHONES,
        "ELEVENLABS_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "APP_TIMEZONE": "America/Chicago",
        "CALL_RESULT_TIMEOUT_S": str(timeout_s),
    }
    settings = load_settings(env_file=None, environ=environ)
    voice = FakeLiveVoice()
    deps = Deps(
        voice=voice,
        intake_model=lambda: FakeNano(),
        rank_client=FakeSuper,
        now=lambda: DEMO_NOW,
        call_result_timeout_s=timeout_s,
    )
    app = create_app(settings, deps=deps)
    client = TestClient(app)
    client.__enter__()
    assert client.get("/api/session").json() == {"ok": True}
    return client, voice


def start(client, key="live-req-1"):
    r = client.post(
        "/api/requests?viewer_id=mary",
        json={"owner_id": "mary", "actor_id": "mary", "text": DEMO_TEXT, "idempotency_key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()["task_id"]


def wait_for(client, task_id, status, timeout=8.0):
    deadline = time.time() + timeout
    task = {}
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()
        if task["status"] == status:
            return task
        if task["status"] in ("failed", "cancelled") and status not in ("failed", "cancelled"):
            raise AssertionError(f"task {task['status']}: {task.get('failure_reason')}")
        time.sleep(0.02)
    raise AssertionError(f"task never reached {status}; last {task.get('status')}")


def wait_until_live(client, task_id, n: int = 3, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with Session(client.app.state.engine) as session:
            rows = list(session.exec(select(Call).where(Call.task_id == task_id)).all())
            if len(rows) >= n and all(c.external_ref and c.status == "live" for c in rows):
                return rows
        time.sleep(0.02)
    raise AssertionError("calls never went live with external_ref")


def post_result(client, *, conversation_id: str, call_id: str, clinic: str):
    body = {
        "type": "post_call_transcription",
        "event_timestamp": int(DEMO_NOW.timestamp()),
        "data": {
            "agent_id": "agent-x",
            "conversation_id": conversation_id,
            "status": "done",
            "transcript": [
                {"role": "agent", "message": "Hi, I'm an AI assistant calling for a patient.", "time_in_call_secs": 1},
                {"role": "user", "message": "We can help.", "time_in_call_secs": 3},
            ],
            "analysis": {"data_collection_results": COLLECTIONS[clinic], "call_successful": "success"},
            "conversation_initiation_client_data": {"dynamic_variables": {"call_id": call_id}},
        },
    }
    raw = json.dumps(body).encode()
    return client.post(
        "/api/webhooks/elevenlabs/post-call",
        content=raw,
        headers={"Content-Type": "application/json", "ElevenLabs-Signature": sign(raw, WEBHOOK_SECRET)},
    )


def test_live_calling_three_webhooks_reach_awaiting_approval(monkeypatch, tmp_path):
    client, voice = make_live_client(monkeypatch, tmp_path)
    task_id = start(client)
    rows = wait_until_live(client, task_id)
    assert len(voice.starts) == 3
    assert {s.call_id for s in voice.starts} == {c.id for c in rows}

    for call in rows:
        r = post_result(client, conversation_id=call.external_ref, call_id=call.id, clinic=call.clinic_name)
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is False and r.json()["complete"] is True

    task = wait_for(client, task_id, "awaiting_approval")
    assert task["decision"]["winner_call_id"]
    events = client.get(f"/api/tasks/{task_id}/events?viewer_id=mary").json()
    live_statuses = [e for e in events if e["type"] == "call_status" and e.get("status") == "live"]
    assert len(live_statuses) == 3
    assert all(e.get("simulated") is False for e in live_statuses)
    results = [e for e in events if e["type"] == "call_result"]
    assert len(results) == 3
    client.__exit__(None, None, None)


def test_live_calling_timeout_marks_missing_and_fails_without_offers(monkeypatch, tmp_path):
    client, voice = make_live_client(monkeypatch, tmp_path, timeout_s=0.35)
    task_id = start(client, key="live-timeout-1")
    wait_until_live(client, task_id)
    assert len(voice.starts) == 3

    task = wait_for(client, task_id, "failed", timeout=5.0)
    assert task["failure_reason"] == "NO_ELIGIBLE_OFFER"
    events = client.get(f"/api/tasks/{task_id}/events?viewer_id=mary").json()
    timeouts = [e for e in events if e["type"] == "call_status" and e.get("reason") == "CALL_TIMEOUT"]
    assert len(timeouts) == 3
    client.__exit__(None, None, None)
