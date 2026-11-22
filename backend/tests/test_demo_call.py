"""Issue #119: scripts/demo_call.py seeds a call the proxy can load, builds the outbound request the proxy expects,
and refuses fixture numbers and off-list entries. No network: place_call is never reached here."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from app.config import load_settings
from app.db import init_db, make_engine
from app.routers.llm_proxy import load_spec

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_call.py"
spec = importlib.util.spec_from_file_location("demo_call", SCRIPT)
demo_call = importlib.util.module_from_spec(spec)
sys.modules["demo_call"] = demo_call  # dataclasses in the script resolve their module through sys.modules
spec.loader.exec_module(demo_call)

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/Chicago"))  # a Monday
ENV = {
    "ELEVENLABS_API_KEY": "key-test", "ELEVENLABS_AGENT_ID": "agent_test", "ELEVENLABS_PHONE_NUMBER_ID": "phnum_test",
    "LLM_PROXY_SECRET": "proxy-secret-test", "PUBLIC_BASE_URL": "https://example.ngrok.app",
    "DEMO_PHONE_ALLOWLIST": "+15550100001,+15550100002,+15555550100",
}


@pytest.fixture
def settings():
    return load_settings(env_file=None, environ=ENV)


def test_seed_writes_a_call_the_proxy_loads_with_the_thursday_afternoon_window(settings):
    engine = make_engine("sqlite://")
    init_db(engine)
    seeded = demo_call.seed(engine, "+15550100001", now=NOW)
    assert seeded.call_id == f"{seeded.task_id[:8]}-A"
    loaded = load_spec(engine, seeded.call_id)
    assert loaded.clinic_name == "Bright Smile Dental" and loaded.care_type == "dental cleaning"
    assert loaded.budget_max == 150 and loaded.insurance_carrier == "Delta Dental"
    starts = sorted((w[0].weekday(), w[0].hour, w[1].hour) for w in loaded.windows)
    assert starts == [(1, 9, 12), (3, 13, 17)], "Tuesday morning and Thursday afternoon"
    assert all(w[0].date() > NOW.date() + timedelta(days=6) for w in loaded.windows), "next week, not this week"


@pytest.mark.parametrize(
    ("today", "expected_dates"),
    [
        (datetime(2026, 11, 22, 18, 0, tzinfo=ZoneInfo("America/Chicago")), [(11, 24), (11, 26)]),  # Sunday: the coming week
        (datetime(2026, 11, 25, 9, 0, tzinfo=ZoneInfo("America/Chicago")), [(12, 1), (12, 3)]),  # Wednesday: the week after this one
    ],
)
def test_windows_fall_in_the_week_after_the_run_day(today, expected_dates):
    """The agent asks for openings next week (#123); on a Sunday rehearsal this week's windows are already past."""
    starts = [datetime.fromisoformat(w["start"]) for w in demo_call.demo_windows(today)]
    assert [d.weekday() for d in starts] == [1, 3] and [d.hour for d in starts] == [9, 13]
    assert [(d.month, d.day) for d in starts] == expected_dates
    assert all(d > today for d in starts), "never a window that has already passed"


def test_outbound_body_carries_call_id_and_secret_where_the_proxy_reads_them(settings):
    body = demo_call.outbound_body(settings, "abc12345-A", "+15550100001")
    extra = body["conversation_initiation_client_data"]["custom_llm_extra_body"]
    assert extra == {"call_id": "abc12345-A", "proxy_secret": "proxy-secret-test"}
    assert body["conversation_initiation_client_data"]["dynamic_variables"] == {"call_id": "abc12345-A"}
    assert body["call_recording_enabled"] is False and body["to_number"] == "+15550100001"
    shown = json.dumps(demo_call.masked(body))
    assert "proxy-secret-test" not in shown and "+15550100001" not in shown and "abc12345-A" in shown


def test_target_number_refuses_fixture_numbers_and_off_list_entries(settings):
    assert demo_call.target_number(settings, 1) == "+15550100001"
    assert demo_call.target_number(settings, 2) == "+15550100002"
    with pytest.raises(demo_call.Refused, match="fixture"):
        demo_call.target_number(settings, 3)
    with pytest.raises(demo_call.Refused, match="between 1 and 3"):
        demo_call.target_number(settings, 4)
    with pytest.raises(demo_call.Refused):
        demo_call.target_number(settings, 0)


def test_database_url_resolves_a_relative_sqlite_path_against_backend(settings):
    url = demo_call.database_url(settings.model_copy(update={"database_url": "sqlite:///./lifeline.db"}))
    assert url.startswith("sqlite:////") and url.endswith("/backend/lifeline.db")
    absolute = "sqlite:////tmp/x.db"
    assert demo_call.database_url(settings.model_copy(update={"database_url": absolute})) == absolute
