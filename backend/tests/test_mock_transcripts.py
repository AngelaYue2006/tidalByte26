"""#87: mock and simulator transcript lines take the live recorder (`llm_proxy.record_turn`) from `Pipeline._voice_event`.

Exactly one Turn row and one transcript event per (call_id, seq), a replayed line is a no-op, lines without a seq are
numbered per call, and `simulated` is kept on the event for mock lines and absent for live ones.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from app.adapters import Deps
from app.db import init_db, make_engine, session_scope
from app.events import EventBus
from app.models import Call, Event, Task, Turn
from app.orchestrator import Pipeline, Run
from app.people import load_owner
from app.routers import llm_proxy
from app.voice_replay import FixtureReplay
from sqlmodel import select

from integrations.types import CallSpec, IntakeRequest
from tests.test_pipeline_mock import FAKE_PHONES

INTAKE = IntakeRequest(care_type="dental cleaning", budget_max=150, insurance_carrier="Delta Dental",
                       time_range={"start": "2026-11-23T00:00:00-06:00", "end": "2026-11-30T00:00:00-06:00"}, needs_ride=True, search_area="Chicago, IL")


@pytest.fixture
def world(monkeypatch):
    """A task with two calls in the database, a Pipeline over it, and a Run the way `Pipeline.run` would build one."""
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", FAKE_PHONES)
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(Task(id="task-87", owner_id="mary", intake_json=INTAKE.model_dump_json(), windows_json="[]"))
        session.flush()
        session.add(Call(id="task-87-a", task_id="task-87", clinic_name="Bright Smile Dental", clinic_phone="+15555550111"))
        session.add(Call(id="task-87-b", task_id="task-87", clinic_name="Smile Co.", clinic_phone="+15555550112"))
    bus = EventBus()
    pipeline = Pipeline(Deps(), engine, bus)
    run = Run(task_id="task-87", owner=load_owner("mary"), text="synthetic")
    recorder = Mock(wraps=llm_proxy.record_turn)
    monkeypatch.setattr(llm_proxy, "record_turn", recorder)
    yield engine, pipeline, run, recorder
    engine.dispose()


def stored(engine):
    with session_scope(engine) as session:
        turns = [(t.call_id, t.seq, t.speaker, t.text) for t in session.exec(select(Turn).order_by(Turn.call_id, Turn.seq))]
        events = [json.loads(e.payload_json) for e in session.exec(select(Event).where(Event.type == "transcript").order_by(Event.id))]
    return turns, events


def line(call_id, text, speaker="agent", seq=None, simulated=True):
    out = {"type": "transcript", "call_id": call_id, "speaker": speaker, "text": text, "simulated": simulated}
    if seq is not None:
        out["seq"] = seq
    return out


def test_a_line_is_one_turn_and_one_event_and_a_replay_adds_nothing(world):
    engine, pipeline, run, recorder = world
    pipeline._voice_event(run, line("task-87-a", "Hi, I'm an AI assistant calling for a patient.", seq=1))
    pipeline._voice_event(run, line("task-87-a", "Sure, how can I help?", speaker="clinic", seq=2))
    pipeline._voice_event(run, line("task-87-a", "Hi, I'm an AI assistant calling for a patient.", seq=1))  # the simulator replays line 1
    pipeline._voice_event(run, line("task-87-a", "Sure, how can I help? (retried wording)", speaker="clinic", seq=2))  # a retry with new wording
    turns, events = stored(engine)
    assert recorder.call_count == 4, "every line reaches the one recorder"
    assert turns == [("task-87-a", 1, "agent", "Hi, I'm an AI assistant calling for a patient."), ("task-87-a", 2, "clinic", "Sure, how can I help?")]
    assert [(e["call_id"], e["seq"], e["speaker"], e["text"]) for e in events] == turns
    assert all(e["simulated"] is True for e in events)
    assert recorder.call_args.kwargs == {"simulated": True} and recorder.call_args.args[2].call_id == "task-87-a"
    assert recorder.call_args.args[2].task_id == "task-87" and recorder.call_args.args[2].clinic_name == "Bright Smile Dental"


def test_lines_without_a_seq_are_numbered_per_call(world):
    engine, pipeline, run, _ = world
    for call_id, text in [("task-87-a", "one"), ("task-87-b", "uno"), ("task-87-a", "two"), ("task-87-b", "dos"), ("task-87-a", "three")]:
        pipeline._voice_event(run, line(call_id, text))
    turns, events = stored(engine)
    assert turns == [("task-87-a", 1, "agent", "one"), ("task-87-a", 2, "agent", "two"), ("task-87-a", 3, "agent", "three"), ("task-87-b", 1, "agent", "uno"), ("task-87-b", 2, "agent", "dos")]
    assert len(events) == 5 and run.transcript_seq == {"task-87-a": 3, "task-87-b": 2}


def test_the_fallback_replay_run_twice_still_leaves_one_row_per_line(world):
    engine, pipeline, run, recorder = world
    spec = CallSpec(clinic={"name": "Bright Smile Dental", "phone_e164": "+15555550111", "address": "123 Main St", "lat": 41.8925, "lng": -87.624, "place_id": "fixture-bright-smile", "simulated": True},
                    request=INTAKE, windows=[], call_id="task-87-a")
    timeline = [payload for _, payload in FixtureReplay().timeline(spec) if payload["type"] == "transcript"]
    assert [p["seq"] for p in timeline] == list(range(1, len(timeline) + 1)) and len(timeline) >= 3
    for payload in timeline + timeline:  # the same call replayed end to end
        pipeline._voice_event(run, payload)
    turns, events = stored(engine)
    assert len(turns) == len(events) == len(timeline) and recorder.call_count == 2 * len(timeline)
    assert turns == [(p["call_id"], p["seq"], p["speaker"], p["text"]) for p in timeline]


def test_status_and_result_events_keep_their_own_path(world):
    engine, pipeline, run, recorder = world
    pipeline._voice_event(run, {"type": "call_status", "call_id": "task-87-a", "status": "live", "simulated": True})
    pipeline._voice_event(run, {"type": "call_result", "call_id": "task-87-a", "price": "$95", "slot": "Thu 9:30", "insured": True, "slotOk": True, "simulated": True})
    assert recorder.call_count == 0
    with session_scope(engine) as session:
        call = session.get(Call, "task-87-a")
        assert call.status == "live" and json.loads(call.result_json)["price"] == "$95"
        assert [e.type for e in session.exec(select(Event).order_by(Event.id))] == ["call_status", "call_result"]


def test_record_turn_labels_only_simulated_lines(world):
    engine, pipeline, _run, _ = world
    spec = llm_proxy.load_spec(engine, "task-87-b")
    llm_proxy.record_turn(engine, pipeline.bus, spec, 1, "agent", "live line")
    llm_proxy.record_turn(engine, pipeline.bus, spec, 2, "clinic", "mock line", simulated=True)
    _, events = stored(engine)
    assert "simulated" not in events[0] and events[1]["simulated"] is True
    assert [e["seq"] for e in events] == [1, 2]
