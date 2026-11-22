"""Single live path with a fake outbound boundary and real signed webhook processing."""

import asyncio
import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app import receipts
from app.adapters import build_deps
from app.config import MissingSetting, load_settings
from app.models import Call, Event, Receipt
from app.routers import llm_proxy, webhooks
from app.voice_live import VoiceLiveBridge
from sqlmodel import Session, select

from integrations import voice_elevenlabs
from integrations.types import CallHandle
from tests.test_config import LIVE_VOICE
from tests.test_pipeline_mock import events, make_client, start, wait_for

PHONE = "+15555550111"  # fictional test phone, never sent to a vendor
SECRET = "test-webhook-secret"


@pytest.fixture
def live_client(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, environ={"ELEVENLABS_WEBHOOK_SECRET": SECRET})
    settings = client.app.state.settings.model_copy(update={
        "voice_mode": "live", "demo_voice_target": PHONE,
    })
    deps = build_deps(settings, client.app.state.engine)
    existing = client.app.state.pipeline.deps
    deps.intake_model, deps.rank_client, deps.now = existing.intake_model, existing.rank_client, existing.now
    client.app.state.pipeline.deps = deps
    monkeypatch.setenv("VOICE_MODE", "live")
    yield client
    client.app.state.pipeline.reset()
    client.__exit__(None, None, None)


def install_dial(monkeypatch, client, *, error=False, simulated=False):
    dialled, ready = [], threading.Event()
    loop_thread = client.portal.call(threading.get_ident)

    def dial(spec):
        # The proxy must be able to resolve this context before the phone rings.
        llm_proxy.load_spec(client.app.state.engine, spec.call_id)
        assert spec.clinic.phone_e164 == PHONE
        assert threading.get_ident() != loop_thread
        dialled.append(spec)
        ready.set()
        if error:
            raise RuntimeError("secret vendor request must never be exposed")
        return CallHandle(call_id=spec.call_id, external_ref="conv_test", simulated=simulated)

    monkeypatch.setattr(voice_elevenlabs, "start_call", dial)
    return dialled, ready


def deliver(client, call_id, *, complete=True, signed=True):
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": int(datetime(2026, 11, 23, 9, tzinfo=ZoneInfo("America/Chicago")).timestamp()),
        "data": {
            "conversation_id": "conv_test",
            "conversation_initiation_client_data": {"dynamic_variables": {"call_id": call_id}},
            "analysis": {"data_collection_results": {
                "price": {"value": "95"}, "insured": {"value": "yes"},
                **({"slot": {"value": "Thursday 9:30 am"}} if complete else {}),
            }},
            "transcript": [],
        },
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["ElevenLabs-Signature"] = webhooks.sign(body, SECRET)
    return client.post("/api/webhooks/elevenlabs/post-call", content=body, headers=headers)


def test_frontend_request_dials_once_and_ranks_only_verified_facts(live_client, monkeypatch):
    client = live_client
    dialled, ready = install_dial(monkeypatch, client)
    task_id = start(client)
    assert ready.wait(3)
    spec = dialled[0]
    assert client.get(f"/api/tasks/{task_id}?viewer_id=mary").json()["status"] == "calling"
    assert len([e for e in events(client, task_id) if e["type"] == "call_start"]) == 1
    assert not next(e for e in events(client, task_id) if e["type"] == "call_start")["simulated"]
    assert deliver(client, spec.call_id, signed=False).status_code == 401
    assert not [e for e in events(client, task_id) if e["type"] == "decision"]
    assert deliver(client, spec.call_id).status_code == 200
    task = wait_for(client, task_id, "awaiting_approval")
    assert task["decision"]["winner_call_id"] == spec.call_id
    assert task["booking"] is None
    assert deliver(client, spec.call_id).json()["duplicate"]
    retry = client.post("/api/requests?viewer_id=mary", json={
        "owner_id": "mary", "actor_id": "mary", "text": "same request",
        "idempotency_key": "req-1",
    })
    assert retry.status_code == 200 and retry.json()["task_id"] == task_id
    assert len(dialled) == 1
    results = [e for e in events(client, task_id) if e["type"] == "call_result"]
    assert len(results) == 1 and results[0]["price"] == "$95"
    engine = client.app.state.engine
    with Session(engine) as session:
        call = session.get(Call, spec.call_id)
        assert call.external_ref == "conv_test"
        assert json.loads(call.result_json)["price_usd"] == 95
    # Re-entering the bridge also reuses the persisted receipt, never dials.
    offers = asyncio.run(client.app.state.pipeline.deps.voice.call_clinics([spec], None))
    route = receipts.payload_of(receipts.find(engine, task_id, f"call:route:{spec.call_id}"))
    assert offers[0].drive_min == route["minutes"]
    assert len(dialled) == 1
    response = client.post(f"/api/tasks/{task_id}/approve?viewer_id=mary", json={
        "actor_id": "mary", "decision": "approve", "idempotency_key": "approve-live",
    })
    assert response.status_code == 200
    failed = wait_for(client, task_id, "failed")
    assert failed["booking"] is None
    assert any(e.get("reason") == "BOOKING_REJECTED" for e in events(client, task_id))
    assert receipts.find(engine, task_id, "calendar") is None


def test_incomplete_live_result_never_becomes_an_offer(live_client, monkeypatch):
    dialled, ready = install_dial(monkeypatch, live_client)
    task_id = start(live_client)
    assert ready.wait(3)
    assert deliver(live_client, dialled[0].call_id, complete=False).status_code == 200
    wait_for(live_client, task_id, "failed")
    assert not [e for e in events(live_client, task_id) if e["type"] in {"call_result", "decision", "booked"}]


@pytest.mark.parametrize("simulated", [False, True])
def test_ambiguous_dial_or_mock_receipt_is_not_retried(live_client, monkeypatch, simulated):
    dialled, ready = install_dial(monkeypatch, live_client, error=not simulated, simulated=simulated)
    task_id = start(live_client)
    assert ready.wait(3)
    wait_for(live_client, task_id, "failed")
    spec = dialled[0]
    with pytest.raises(RuntimeError, match="unknown outcome"):
        asyncio.run(live_client.app.state.pipeline.deps.voice.call_clinics([spec], None))
    assert len(dialled) == 1
    assert "secret vendor" not in json.dumps(events(live_client, task_id))


def test_allowlist_is_rechecked_before_dial(live_client, monkeypatch):
    dialled, ready = install_dial(monkeypatch, live_client)
    # Discovery refuses before a call is created or the vendor boundary runs.
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "+15555550100")
    task_id = start(live_client)
    wait_for(live_client, task_id, "failed")
    assert not ready.is_set() and dialled == []


def test_missing_route_never_dials_and_timeout_never_invents_a_result(live_client, monkeypatch):
    dialled, ready = install_dial(monkeypatch, live_client)
    start(live_client)
    assert ready.wait(3)
    spec = dialled[0]
    engine = live_client.app.state.engine
    bridge = VoiceLiveBridge(engine, timeout_s=0)
    with pytest.raises(RuntimeError, match="Timed out"):
        asyncio.run(bridge.call_clinics([spec], None))
    with Session(engine) as session:
        assert session.get(Call, spec.call_id).result_json is None
        route = session.exec(select(Receipt).where(Receipt.step == f"call:route:{spec.call_id}")).one()
        session.delete(route)
        session.commit()
    with pytest.raises(RuntimeError, match="distance"):
        asyncio.run(bridge.call_clinics([spec], None))
    assert len(dialled) == 1
    with Session(engine) as session:
        assert not session.exec(select(Event).where(Event.type == "call_result")).all()


@pytest.mark.parametrize("target", ["", "+15550100009"])
def test_live_startup_needs_an_explicit_allowlisted_target(target):
    with pytest.raises(MissingSetting, match="DEMO_VOICE_TARGET"):
        load_settings(env_file=None, environ={**LIVE_VOICE, "DEMO_VOICE_TARGET": target}).validate_startup()


def test_live_startup_rejects_the_twilio_sender_as_destination():
    with pytest.raises(MissingSetting, match="Twilio sender"):
        load_settings(env_file=None, environ={**LIVE_VOICE, "TWILIO_PHONE_NUMBER": LIVE_VOICE["DEMO_VOICE_TARGET"]}).validate_startup()


def test_first_live_proxy_turn_marks_connected_once(live_client, monkeypatch):
    dialled, ready = install_dial(monkeypatch, live_client)
    task_id = start(live_client)
    assert ready.wait(3)
    spec = dialled[0]
    engine, bus = live_client.app.state.engine, live_client.app.state.bus
    context = llm_proxy.load_spec(engine, spec.call_id)
    llm_proxy.record_turn(engine, bus, context, 1, "clinic", "Synthetic receptionist greeting")
    llm_proxy.record_turn(engine, bus, context, 1, "clinic", "Synthetic receptionist greeting")
    connected = [e for e in events(live_client, task_id) if e["type"] == "call_status" and e["status"] == "live"]
    assert len(connected) == 1
    assert deliver(live_client, spec.call_id).status_code == 200
    wait_for(live_client, task_id, "awaiting_approval")
    llm_proxy.record_turn(engine, bus, context, 2, "agent", "Synthetic late turn")
    with Session(engine) as session:
        assert session.get(Call, spec.call_id).status == "done"
