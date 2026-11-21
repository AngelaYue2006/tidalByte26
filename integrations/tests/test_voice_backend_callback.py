"""Exercise the real mock bridge and backend sink against a synthetic database.

The pending common-recorder contract is a strict expected failure, never claimed
as completed acceptance. No vendor requests or real people's data are used.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlmodel import select

from integrations.fixtures import read_fixture
from integrations.google_calendar import free_windows
from integrations.google_places import find_clinics
from integrations.types import CallSpec, IntakeRequest


async def instant(_seconds):
    await asyncio.sleep(0)


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    from app import orchestrator
    from app.adapters import Deps, VoiceMockBridge
    from app.db import init_db, make_engine, session_scope
    from app.events import EventBus
    from app.models import Call, Event, Task, Turn
    from app.orchestrator import Pipeline, Run
    from app.people import load_owner
    from app.routers import llm_proxy

    monkeypatch.setenv("VOICE_MODE", "mock")
    monkeypatch.setenv("PLACES_MODE", "fixture")
    monkeypatch.setenv("CALENDAR_MODE", "mock")
    clinics = read_fixture("clinics.json")["clinics"]
    monkeypatch.setenv(
        "DEMO_PHONE_ALLOWLIST", ",".join(c["phone_e164"] for c in clinics)
    )
    request = IntakeRequest(
        care_type="dental cleaning",
        budget_max=150,
        insurance_carrier="Delta Dental",
        time_range={"start": "2026-11-23T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
        needs_ride=True,
        search_area="Chicago, IL",
    )
    windows = free_windows(
        "mary", request.time_range.start.isoformat(), request.time_range.end.isoformat()
    )
    calls = [
        CallSpec(clinic=c, request=request, windows=windows, call_id=f"test-{i}")
        for i, c in enumerate(find_clinics("dental cleaning", "Chicago, IL"))
    ]
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(
            Task(
                id="test-task",
                owner_id="mary",
                intake_json=request.model_dump_json(),
                windows_json=json.dumps([w.model_dump(mode="json") for w in windows]),
            )
        )
        session.flush()
        for call in calls:
            session.add(
                Call(
                    id=call.call_id,
                    task_id="test-task",
                    clinic_name=call.clinic.name,
                    clinic_phone=call.clinic.phone_e164,
                )
            )
    bus = EventBus()
    pipeline = Pipeline(Deps(), engine, bus)
    run = Run(
        task_id="test-task", owner=load_owner("mary"), text="Synthetic fixture request"
    )
    recorder = Mock(wraps=llm_proxy.record_turn)
    monkeypatch.setattr(llm_proxy, "record_turn", recorder)
    if hasattr(orchestrator, "record_turn"):
        monkeypatch.setattr(orchestrator, "record_turn", recorder)

    async def replay_calls():
        return await VoiceMockBridge(sleep=instant).call_clinics(
            calls, lambda event: pipeline._voice_event(run, event)
        )

    offers = asyncio.run(replay_calls())
    with session_scope(engine) as session:
        events = list(session.exec(select(Event).order_by(Event.id)).all())
        turns = list(session.exec(select(Turn).order_by(Turn.call_id, Turn.seq)).all())
        saved_calls = list(session.exec(select(Call)).all())
        session.expunge_all()
    yield offers, events, turns, saved_calls, recorder
    engine.dispose()


def test_real_backend_sink_receives_three_simulated_calls(replay):
    offers, events, _, calls, _ = replay
    assert len(offers) == len(calls) == 3
    assert all(c.status == "done" and c.result_json for c in calls)
    assert all(json.loads(event.payload_json)["simulated"] for event in events)
    assert sum(event.type == "call_result" for event in events) == 3
    assert any(
        json.loads(event.payload_json).get("status") == "hold" for event in events
    )
    assert all(event.visibility == "contact" for event in events)
    for call in calls:
        lines = [
            json.loads(e.payload_json)
            for e in events
            if e.type == "transcript"
            and json.loads(e.payload_json)["call_id"] == call.id
        ]
        assert [line["seq"] for line in lines] == list(range(1, len(lines) + 1))
        first_agent = next(line for line in lines if line["speaker"] == "agent")
        assert first_agent["text"].startswith(
            "Hi, I'm an AI assistant calling for a patient."
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Backend sink bypasses the common proxy recorder; Joyce must wire it and preserve simulated=true",
)
def test_mock_transcripts_use_the_same_recorder_as_live_proxy(replay):
    _, events, turns, _, recorder = replay
    transcripts = [json.loads(e.payload_json) for e in events if e.type == "transcript"]
    assert recorder.call_count == len(transcripts)
    assert len(turns) == len(transcripts)
    assert {(t.call_id, t.seq, t.speaker, t.text) for t in turns} == {
        (line["call_id"], line["seq"], line["speaker"], line["text"])
        for line in transcripts
    }
    assert all(line.get("simulated") is True for line in transcripts)
