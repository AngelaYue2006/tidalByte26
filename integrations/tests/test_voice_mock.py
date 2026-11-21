"""Scripted voice adapter contracts, safety boundaries and concurrent playback."""

import asyncio
import json
import socket
import time
from pathlib import Path

import jsonschema
import pytest

from integrations import voice_mock as voice
from integrations.fixtures import read_fixture
from integrations.google_calendar import free_windows
from integrations.google_places import find_clinics
from integrations.types import CallHandle, CallSpec, Confirmation, IntakeRequest, Offer


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "mock")
    monkeypatch.setenv("PLACES_MODE", "fixture")
    monkeypatch.setenv("CALENDAR_MODE", "mock")
    clinics = read_fixture("clinics.json")["clinics"]
    monkeypatch.setenv(
        "DEMO_PHONE_ALLOWLIST", ",".join(c["phone_e164"] for c in clinics)
    )

    original_connect = socket.socket.connect

    def no_network(sock, address):
        # Windows asyncio creates an internal loopback socket pair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        pytest.fail("Mock voice attempted external network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)


@pytest.fixture
def calls():
    windows = free_windows("mary", "2026-11-23T00:00:00Z", "2026-12-01T00:00:00Z")
    request = IntakeRequest(
        care_type="dental cleaning",
        budget_max=150,
        insurance_carrier="Delta Dental",
        time_range={"start": "2026-11-23T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
        needs_ride=True,
        search_area=None,
    )
    return [
        CallSpec(clinic=clinic, request=request, windows=windows, call_id=f"demo-{i}")
        for i, clinic in enumerate(find_clinics("dental cleaning", "near home"))
    ]


async def instant_sleep(seconds):
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_replays_schema_valid_facts_to_callback(calls):
    events = []
    schema_path = Path(__file__).resolve().parents[2] / "shared" / "events.schema.json"
    schema = json.loads(schema_path.read_text())
    async with voice.callbacks(events.append, sleep=instant_sleep) as session:
        handles = [voice.start_call(call) for call in calls]
        offers = await asyncio.gather(
            *(session.wait_call(handle) for handle in handles)
        )
    assert all(
        isinstance(handle, CallHandle) and handle.simulated for handle in handles
    )
    assert all(isinstance(offer, Offer) for offer in offers)
    assert [offer.price for offer in offers] == [95, 120, 140]
    assert [offer.distance_mi for offer in offers] == [1.2, 0.6, 3.4]
    for event in events:
        jsonschema.validate(event, schema)
        assert event["simulated"] is True
    for call in calls:
        own = [event for event in events if event["call_id"] == call.call_id]
        assert own[0]["status"] == "dialing"
        assert own[-1]["type"] == "call_result"
        lines = [event for event in own if event["type"] == "transcript"]
        assert [event["seq"] for event in lines] == list(range(1, len(lines) + 1))
        first_agent = next(e for e in own if e.get("speaker") == "agent")
        assert first_agent["text"].startswith(
            "Hi, I'm an AI assistant calling for a patient."
        )
    assert any(event.get("status") == "hold" for event in events)
    results = [event for event in events if event["type"] == "call_result"]
    assert [
        event["slotOk"] for event in sorted(results, key=lambda e: e["call_id"])
    ] == [True, False, False]


@pytest.mark.asyncio
async def test_retry_reuses_handle_without_duplicate_events(calls):
    events = []
    async with voice.callbacks(events.append, sleep=instant_sleep) as session:
        handle = voice.start_call(calls[0])
        assert handle == voice.start_call(calls[0])
        await session.wait_call(handle)
        count = len(events)
        assert handle == voice.start_call(calls[0])
        await session.wait_call(handle)
        assert len(events) == count
        changed = calls[0].model_copy(deep=True)
        changed.request.budget_max = 100
        with pytest.raises(RuntimeError, match="different"):
            voice.start_call(changed)


@pytest.mark.asyncio
async def test_callback_failure_is_observable_and_session_is_closed(calls):
    async def fail(event):
        raise RuntimeError("synthetic callback failure")

    with pytest.raises(RuntimeError, match="callback failure"):
        async with voice.callbacks(fail, sleep=instant_sleep) as session:
            handle = voice.start_call(calls[0])
            await session.wait_call(handle)
    assert session.closed


@pytest.mark.asyncio
async def test_nested_sessions_keep_callbacks_isolated(calls):
    outer_events, inner_events = [], []
    async with voice.callbacks(outer_events.append, sleep=instant_sleep) as outer:
        outer_handle = voice.start_call(calls[0])
        async with voice.callbacks(inner_events.append, sleep=instant_sleep) as inner:
            inner_handle = voice.start_call(calls[1])
            await inner.wait_call(inner_handle)
        await outer.wait_call(outer_handle)
    assert {event["call_id"] for event in outer_events} == {calls[0].call_id}
    assert {event["call_id"] for event in inner_events} == {calls[1].call_id}


def test_booking_returns_confirmed_and_tentative_receipts(calls):
    rows = read_fixture("receptionists.json")["receptionists"]
    confirmed = voice.confirm_booking(calls[0], rows[0]["result"]["slot_start"])
    assert isinstance(confirmed, Confirmation) and confirmed.simulated
    assert confirmed.status == "confirmed" and confirmed.confirmation_ref.startswith(
        "mock-"
    )
    assert confirmed == voice.confirm_booking(calls[0], rows[0]["result"]["slot_label"])
    tentative = voice.confirm_booking(calls[2], rows[2]["result"]["slot_start"])
    assert tentative.status == "tentative" and tentative.confirmation_ref is None
    with pytest.raises(RuntimeError, match="slot"):
        voice.confirm_booking(calls[0], "2030-01-01T00:00:00Z")


@pytest.mark.asyncio
async def test_calls_and_callbacks_fail_closed(calls, monkeypatch):
    with pytest.raises(RuntimeError, match="callbacks"):
        voice.start_call(calls[0])
    async with voice.callbacks(lambda event: None, sleep=instant_sleep):
        monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", "")
        with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
            voice.start_call(calls[0])
        with pytest.raises(RuntimeError, match="UNVERIFIED_SENDER"):
            voice.confirm_booking(calls[0], "Thu 9:30")
        monkeypatch.setenv("VOICE_MODE", "live")
        with pytest.raises(RuntimeError, match="mock"):
            voice.start_call(calls[0])


@pytest.mark.asyncio
async def test_three_calls_real_time_overlap_with_a_hold(calls):
    observations = []
    started = time.monotonic()
    async with voice.callbacks(
        lambda event: observations.append((time.monotonic(), event))
    ) as session:
        handles = [voice.start_call(call) for call in calls]
        await asyncio.gather(*(session.wait_call(handle) for handle in handles))
    duration = time.monotonic() - started
    dial_times = [at for at, event in observations if event.get("status") == "dialing"]
    assert len(dial_times) == 3 and max(dial_times) - min(dial_times) < 2
    assert 15 <= duration < 25  # Longest fixture is 15.2s; serial replay exceeds 30s.
    bright_agent_times = [
        at
        for at, event in observations
        if event["call_id"] == calls[0].call_id and event.get("speaker") == "agent"
    ]
    assert 1 <= bright_agent_times[0] - min(dial_times) <= 3
    assert any(event.get("status") == "hold" for _, event in observations)


@pytest.mark.asyncio
async def test_context_failure_cancels_pending_replay(calls):
    cancelled = asyncio.Event()
    events = []

    async def blocked_sleep(seconds):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(ValueError, match="pipeline cancelled"):
        async with voice.callbacks(events.append, sleep=blocked_sleep) as session:
            voice.start_call(calls[0])
            await asyncio.sleep(0)
            raise ValueError("pipeline cancelled")
    assert cancelled.is_set() and session.closed and events == []


@pytest.mark.asyncio
async def test_missing_ai_disclosure_fails_before_any_callback(calls, monkeypatch):
    from integrations import receptionist_script

    fixture = read_fixture("receptionists.json")
    fixture["receptionists"][0]["lines"][0]["text"] = "Hello."
    original = receptionist_script.read_fixture
    monkeypatch.setattr(
        receptionist_script,
        "read_fixture",
        lambda name: fixture if name == "receptionists.json" else original(name),
    )
    events = []
    async with voice.callbacks(events.append, sleep=instant_sleep):
        with pytest.raises(RuntimeError, match="AI disclosure"):
            voice.start_call(calls[0])
    assert events == []
