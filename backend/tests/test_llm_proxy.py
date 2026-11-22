"""Issue #20: the custom-LLM proxy checks the secret, finds the call, builds the redacted prompt, relays Lightning's stream and logs turns."""

import json
import logging
from datetime import UTC, datetime

import pytest
from app.config import load_settings
from app.db import session_scope
from app.events import Viewer, list_events
from app.main import create_app
from app.models import Call, Contact, Event, Task, Turn
from app.nemotron.call_agent import (
    LightningClient,
    build_messages,
    delta_text,
    relay,
    strip_reasoning,
)
from app.nemotron.prompts import OPENING_LINE, call_agent, window_label
from app.nemotron.types import CallSpec
from fastapi.testclient import TestClient
from sqlmodel import select

PROXY_SECRET = "proxy-canary-0123456789"
RAW_UTTERANCE = "I need a cleaning this week, under $150, I have Delta Dental, member DEMO-0000-0000-0001, my knee makes walking hard"
ENV = {
    "APP_ENV": "development",
    "DATABASE_URL": "sqlite://",
    "LLM_PROXY_SECRET": PROXY_SECRET,
    "NEMOTRON_LIGHTNING_ID": "nvidia/lightning-test",
}
INTAKE = {
    "care_type": "dental cleaning",
    "budget_max": 150,
    "insurance_carrier": "Delta Dental",
    "time_range": {"start": "2026-11-23T00:00:00-06:00", "end": "2026-11-29T23:59:59-06:00"},
    "needs_ride": True,
    "search_area": "Chicago, IL",
    "dropped_fields": ["member_id", "mobility_details"],
}
WINDOWS = [
    {"start": "2026-11-24T13:00:00-06:00", "end": "2026-11-24T17:00:00-06:00"},
    {"start": "2026-11-26T08:00:00-06:00", "end": "2026-11-26T12:00:00-06:00"},
]


def chunk(text, finish=None):
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "nvidia/lightning-test",
        "choices": [{"index": 0, "delta": {"content": text} if text else {}, "finish_reason": finish}],
    }


class FakeLightning:
    model_id = "nvidia/lightning-test"

    def __init__(self, *pieces):
        self.pieces = list(pieces) or ["Yes. ", "Do you take ", "Delta Dental?"]
        self.requests: list[list[dict]] = []

    def stream_chat(self, messages):
        self.requests.append(messages)
        for piece in self.pieces:
            yield chunk(piece)
        yield chunk("", finish="stop")


def body(*, messages=None, extra=None, stream=True, **overrides):
    payload = {
        "model": "lifeline-lightning",
        "messages": messages
        or [
            {"role": "system", "content": "ElevenLabs default agent prompt"},
            {"role": "assistant", "content": OPENING_LINE + " Do you take Delta Dental?"},
            {"role": "user", "content": "Yes, we do. A cleaning is $95 with Delta."},
        ],
        "temperature": 0.5,
        "max_tokens": 5000,
        "stream": stream,
        "elevenlabs_extra_body": {"call_id": "call-a", "proxy_secret": PROXY_SECRET} if extra is None else extra,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def metrics_file(tmp_path, monkeypatch):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("METRICS_PATH", str(path))
    return path


@pytest.fixture
def app(metrics_file):
    app = create_app(load_settings(env_file=None, environ=ENV))
    app.state.lightning_client = FakeLightning()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        with session_scope(app.state.engine) as s:
            s.add(Task(id="task-1", owner_id="mary", status="calling", intake_json=json.dumps(INTAKE), windows_json=json.dumps(WINDOWS)))
            s.add(Call(id="call-a", task_id="task-1", clinic_name="Bright Smile Dental", clinic_phone="+15555550111", status="live"))
            s.add(Contact(id="sarah", owner_id="mary", name="Sarah Johnson", phone_e164="+15555550101", relationship="daughter"))
        yield c


def turns(app, call_id="call-a"):
    with session_scope(app.state.engine) as s:
        rows = s.exec(select(Turn).where(Turn.call_id == call_id).order_by(Turn.seq)).all()
        return [(t.seq, t.speaker, t.text) for t in rows]


def sse_chunks(text):
    lines = [line for line in text.split("\n\n") if line.strip()]
    assert all(line.startswith("data: ") for line in lines)
    assert lines[-1] == "data: [DONE]"
    return [json.loads(line[6:]) for line in lines[:-1]]


# --- auth -----------------------------------------------------------------------------------------


def test_missing_secret_is_rejected(client):
    r = client.post("/v1/chat/completions", json=body(extra={"call_id": "call-a"}))
    assert r.status_code == 401


def test_wrong_secret_is_rejected_and_nothing_is_logged(client, app):
    r = client.post("/v1/chat/completions", json=body(extra={"call_id": "call-a", "proxy_secret": "nope"}))
    assert r.status_code == 401
    assert turns(app) == []
    assert app.state.lightning_client.requests == []


def test_bearer_header_carries_the_same_secret(client):
    r = client.post("/v1/chat/completions", json=body(extra={"call_id": "call-a"}), headers={"Authorization": f"Bearer {PROXY_SECRET}"})
    assert r.status_code == 200


def test_unset_secret_in_env_fails_closed():
    app = create_app(load_settings(env_file=None, environ={k: v for k, v in ENV.items() if k != "LLM_PROXY_SECRET"}))
    app.state.lightning_client = FakeLightning()
    with TestClient(app) as c:
        assert c.post("/v1/chat/completions", json=body()).status_code == 503


# --- call lookup ------------------------------------------------------------------------------------


def test_missing_call_id_is_a_400(client):
    r = client.post("/v1/chat/completions", json=body(extra={"proxy_secret": PROXY_SECRET}))
    assert r.status_code == 400
    assert "call_id" in r.json()["detail"]


def test_unknown_call_id_is_a_404(client):
    r = client.post("/v1/chat/completions", json=body(extra={"call_id": "call-zzz", "proxy_secret": PROXY_SECRET}))
    assert r.status_code == 404


def test_non_json_body_is_a_400(client):
    r = client.post("/v1/chat/completions", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


# --- streaming relay --------------------------------------------------------------------------------


def test_stream_relays_openai_chunks_and_ends_with_done(client, app):
    r = client.post("/v1/chat/completions", json=body())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    chunks = sse_chunks(r.text)
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert "".join(delta_text(c) for c in chunks) == "Yes. Do you take Delta Dental?"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_turns_are_written_for_clinic_and_agent(client, app):
    client.post("/v1/chat/completions", json=body())
    assert turns(app) == [
        (2, "clinic", "Yes, we do. A cleaning is $95 with Delta."),
        (3, "agent", "Yes. Do you take Delta Dental?"),
    ]


def test_each_turn_is_one_transcript_event_both_roles_can_see(client, app):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    client.post("/v1/chat/completions", json=body())
    shared = Path(__file__).resolve().parents[2] / "shared"
    schemas = [json.loads((shared / n).read_text()) for n in ("events.schema.json", "intake_request.schema.json", "decision.schema.json", "task.schema.json")]
    validator = Draft202012Validator(schemas[0], registry=Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas]), format_checker=FormatChecker())
    with session_scope(app.state.engine) as s:
        rows = s.exec(select(Event).where(Event.task_id == "task-1").order_by(Event.id)).all()
        assert [(r.type, r.visibility) for r in rows] == [("transcript", "contact"), ("transcript", "contact")]
        for role in ("owner", "contact"):
            events = list_events(s, "task-1", Viewer(id="x", role=role, owner_id="mary"))
            assert [(e["speaker"], e["text"]) for e in events] == [
                ("clinic", "Yes, we do. A cleaning is $95 with Delta."),
                ("agent", "Yes. Do you take Delta Dental?"),
            ]
            for e in events:
                assert e["call_id"] == "call-a"
                validator.validate({k: v for k, v in e.items() if k != "id"})


def test_retry_replays_the_recorded_turn_without_calling_lightning(client, app, caplog):
    """#90: ElevenLabs re-sends the same conversation (a retry, or a re-ask after the receptionist spoke over the agent).
    The proxy speaks the recorded line, writes nothing new and never reaches Lightning, so speech and transcript agree."""
    client.post("/v1/chat/completions", json=body())
    app.state.lightning_client.pieces = ["Sure, ", "do you take Delta?"]  # Lightning would word a retry differently
    with caplog.at_level(logging.INFO, logger="lifeline.llm_proxy"):
        r = client.post("/v1/chat/completions", json=body())  # ElevenLabs retry with the same history
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    deltas = [json.loads(ln[6:])["choices"][0]["delta"].get("content", "") for ln in lines[:-1]]
    assert "".join(deltas) == "Yes. Do you take Delta Dental?", "the recorded line, not Lightning's new wording"
    assert json.loads(lines[-2][6:])["choices"][0]["finish_reason"] == "stop"
    assert len(app.state.lightning_client.requests) == 1, "Lightning answered once; the retry was a replay"
    assert "replaying recorded turn 3" in caplog.text
    assert turns(app) == [
        (2, "clinic", "Yes, we do. A cleaning is $95 with Delta."),
        (3, "agent", "Yes. Do you take Delta Dental?"),
    ]
    with session_scope(app.state.engine) as s:
        assert len(s.exec(select(Event).where(Event.type == "transcript")).all()) == 2


def test_non_streaming_retry_replays_the_recorded_turn(client, app, metrics_file):
    client.post("/v1/chat/completions", json=body(stream=False))
    app.state.lightning_client.pieces = ["Something else."]
    r = client.post("/v1/chat/completions", json=body(stream=False))
    assert r.status_code == 200
    assert r.json()["object"] == "chat.completion" and r.json()["choices"][0]["message"] == {"role": "assistant", "content": "Yes. Do you take Delta Dental?"}
    assert r.json()["choices"][0]["finish_reason"] == "stop"
    assert len(app.state.lightning_client.requests) == 1
    assert len(turns(app)) == 2
    assert metrics_file.read_text().count('"call_agent"') == 1, "no first-token row for a replay: nothing was generated"


def test_a_genuine_repeated_line_later_in_the_call_is_kept(client, app):
    history = body()["messages"]
    client.post("/v1/chat/completions", json=body(messages=history))
    app.state.lightning_client.pieces = ["Okay."]
    history = history + [{"role": "assistant", "content": "Yes. Do you take Delta Dental?"}, {"role": "user", "content": "Okay."}]
    client.post("/v1/chat/completions", json=body(messages=history))
    history = history + [{"role": "assistant", "content": "Okay."}, {"role": "user", "content": "Okay."}]
    client.post("/v1/chat/completions", json=body(messages=history))
    assert [t[1:] for t in turns(app)] == [
        ("clinic", "Yes, we do. A cleaning is $95 with Delta."),
        ("agent", "Yes. Do you take Delta Dental?"),
        ("clinic", "Okay."),
        ("agent", "Okay."),
        ("clinic", "Okay."),
        ("agent", "Okay."),
    ]
    with session_scope(app.state.engine) as s:
        payloads = [json.loads(e.payload_json) for e in s.exec(select(Event).where(Event.type == "transcript").order_by(Event.id)).all()]
    assert [p["seq"] for p in payloads] == [2, 3, 4, 5, 6, 7]


def test_overlapping_retries_write_exactly_one_turn_and_one_event(tmp_path):
    import threading

    from app.nemotron.types import CallSpec
    from app.routers.llm_proxy import record_turn

    app = create_app(load_settings(env_file=None, environ={**ENV, "DATABASE_URL": f"sqlite:///{tmp_path}/race.db"}))
    with TestClient(app):
        with session_scope(app.state.engine) as s:
            s.add(Task(id="task-1", owner_id="mary", status="calling", intake_json="{}", windows_json="[]"))
            s.add(Call(id="call-a", task_id="task-1", clinic_name="Bright Smile Dental", clinic_phone="+15555550111"))
        spec = CallSpec(call_id="call-a", task_id="task-1", clinic_name="Bright Smile Dental", care_type="dental cleaning")
        barrier = threading.Barrier(8)
        written = []

        def complete(i):
            barrier.wait()
            written.append(record_turn(app.state.engine, app.state.bus, spec, 3, "agent", f"wording {i}") is not None)

        threads = [threading.Thread(target=complete, args=(i,)) for i in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert written.count(True) == 1
        assert len(turns(app)) == 1
        with session_scope(app.state.engine) as s:
            rows = s.exec(select(Event).where(Event.type == "transcript")).all()
            assert len(rows) == 1 and json.loads(rows[0].payload_json)["seq"] == 3


def test_existing_database_without_the_index_gets_it_at_startup(tmp_path):
    import sqlite3

    from app.db import init_db, make_engine
    from app.models import TURNS_UNIQUE_INDEX
    from sqlalchemy.exc import IntegrityError

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)  # the pre-#20 shape: every table, turns without the unique index
    con.executescript(
        "CREATE TABLE tasks (id VARCHAR PRIMARY KEY, owner_id VARCHAR NOT NULL, status VARCHAR NOT NULL, intake_json VARCHAR, windows_json VARCHAR, decision_json VARCHAR, booking_json VARCHAR, transport_json VARCHAR, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);"
        "CREATE TABLE calls (id VARCHAR PRIMARY KEY, task_id VARCHAR NOT NULL, clinic_name VARCHAR NOT NULL, clinic_phone VARCHAR NOT NULL, distance_mi FLOAT, status VARCHAR NOT NULL, result_json VARCHAR, external_ref VARCHAR, started_at DATETIME, ended_at DATETIME);"
        "CREATE TABLE turns (id VARCHAR PRIMARY KEY, call_id VARCHAR NOT NULL, seq INTEGER NOT NULL, speaker VARCHAR NOT NULL, text VARCHAR NOT NULL, at DATETIME NOT NULL);"
        "INSERT INTO tasks VALUES ('t','mary','calling',NULL,NULL,NULL,NULL,NULL,'2026-01-01','2026-01-01');"
        "INSERT INTO calls VALUES ('c','t','Oak','+15555550113',NULL,'live',NULL,NULL,NULL,NULL);"
    )
    con.commit()
    con.close()
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    indexes = {row[1] for row in sqlite3.connect(path).execute("PRAGMA index_list('turns')")}
    assert TURNS_UNIQUE_INDEX in indexes
    with session_scope(engine) as s:
        s.add(Turn(call_id="c", seq=1, speaker="agent", text="a"))
    with pytest.raises(IntegrityError), session_scope(engine) as s:
        s.add(Turn(call_id="c", seq=1, speaker="agent", text="b"))
    init_db(engine)  # idempotent on the next start


def test_contact_sees_clinic_lines_screened_and_owner_sees_them_as_spoken(client, app):
    leaky = "Sure. I have the patient down as member DEMO-0000-0000-0001, born 03/14/1948, call back on 312-555-0142. Thursday at 9:30 is open."
    client.post("/v1/chat/completions", json=body())  # first turn: the clinic's price line
    history = body()["messages"] + [{"role": "assistant", "content": "Yes. Do you take Delta Dental?"}, {"role": "user", "content": leaky}]
    client.post("/v1/chat/completions", json=body(messages=history))
    with session_scope(app.state.engine) as s:
        contact = [e for e in list_events(s, "task-1", Viewer(id="sarah", role="contact", owner_id="mary")) if e.get("speaker") == "clinic"]
        owner = [e for e in list_events(s, "task-1", Viewer(id="mary", role="owner", owner_id="mary")) if e.get("speaker") == "clinic"]
    assert owner[-1]["text"] == leaky
    screened = contact[-1]["text"]
    for identifier in ("DEMO-0000-0000-0001", "03/14/1948", "312-555-0142"):
        assert identifier not in screened
    assert "Thursday at 9:30 is open." in screened and "[removed]" in screened
    assert contact[0]["text"] == "Yes, we do. A cleaning is $95 with Delta."  # a price is a fact the contact may see


def test_turn_and_event_are_written_together_or_not_at_all(client, app, monkeypatch):
    from app.routers import llm_proxy

    class Boom(Exception):
        pass

    def exploding_event(**kwargs):
        raise Boom("event row write failed")

    monkeypatch.setattr(llm_proxy, "Event", exploding_event)
    with pytest.raises(Boom):
        client.post("/v1/chat/completions", json=body())
    assert turns(app) == []
    with session_scope(app.state.engine) as s:
        assert s.exec(select(Event)).all() == []


def test_first_turn_without_a_clinic_line_writes_only_the_agent(client, app):
    client.post("/v1/chat/completions", json=body(messages=[{"role": "system", "content": "x"}]))
    assert [t[1] for t in turns(app)] == ["agent"]


def test_first_token_latency_is_one_metrics_row_with_numbers_only(client, metrics_file):
    client.post("/v1/chat/completions", json=body())
    (line,) = metrics_file.read_text().splitlines()
    row = json.loads(line)
    assert row["kind"] == "call_agent"
    assert row["call_id"] == "call-a"
    assert row["model"] == "nvidia/lightning-test"
    assert isinstance(row["first_token_ms"], int) and 0 <= row["first_token_ms"] < 5000
    assert "Delta" not in line and "text" not in row


def test_non_streaming_request_returns_a_chat_completion(client, app):
    r = client.post("/v1/chat/completions", json=body(stream=False))
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"] == {"role": "assistant", "content": "Yes. Do you take Delta Dental?"}
    assert turns(app)[-1][1:] == ("agent", "Yes. Do you take Delta Dental?")


# --- what goes upstream -----------------------------------------------------------------------------


def test_upstream_gets_our_prompt_and_only_redacted_facts(client, app):
    client.post("/v1/chat/completions", json=body())
    (messages,) = app.state.lightning_client.requests
    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert OPENING_LINE in system
    for fact in ("Bright Smile Dental", "dental cleaning", "Delta Dental", "Tue 1:00–5:00", "Thu 8:00–12:00"):
        assert fact in system
    # #123: the receptionist never hears the budget; the hard rules apply it after the call
    assert "$150" not in system and "150" not in system and "budget" not in system.lower().replace("the patient's budget", "")
    serialised = json.dumps(messages)
    for secret in ("DEMO-0000", "knee", "Mary", "member_id", "ElevenLabs default agent prompt", "elevenlabs_extra_body", PROXY_SECRET):
        assert secret not in serialised
    assert [m["role"] for m in messages] == ["system", "assistant", "user"]
    assert RAW_UTTERANCE not in serialised


def test_prompt_discloses_ai_and_never_books():
    spec = CallSpec(call_id="c", task_id="t", clinic_name="Oak Dental", care_type="dental cleaning", windows=[(datetime(2026, 11, 26, 8, tzinfo=UTC), datetime(2026, 11, 26, 12, tzinfo=UTC))])
    prompt = call_agent(spec)
    assert prompt.count(OPENING_LINE) == 1
    # #90: the first message is spoken by the agent's configured greeting before the proxy is ever asked; on the first
    # live call the prompt's "first words, exactly" made Lightning repeat the greeting on every turn.
    assert "already opened with your first message" in prompt and "Never say it again" in prompt
    assert "Your next line is question 1" in prompt and "in one sentence" in prompt
    assert "Never repeat a sentence you already said" in prompt
    assert "first words" not in prompt.lower()
    # #94: on the second live call the agent asked the receptionist what the patient would consider when the offered
    # slot fell outside the windows, so the call ended with no slot. The agent collects facts; the patient decides later.
    assert "say it does not fit and ask for the earliest time inside the windows" in prompt
    assert "take their earliest time and say the patient will be asked" in prompt
    assert "Never ask the receptionist what the patient would consider" in prompt
    assert "ask for the earliest they have and note it" not in prompt
    # Third live call: with a valid time the agent recited the collected facts back to the receptionist. The ending is
    # now fixed: thank them, say the patient's assistant will call back to book, end. Never book, hold or confirm stays.
    assert "Ending: once you know the insurance answer, the price and a time, thank them, say the patient's assistant will call back to book, and end the call." in prompt
    assert "Never summarise or repeat the collected details" in prompt
    assert "Never book, hold or confirm an appointment" in prompt
    assert "hold that time" not in prompt and "say goodbye in one sentence" not in prompt
    assert "You are an AI" in prompt
    assert "Never book" in prompt
    assert "no insurance to mention" in prompt
    assert window_label(*spec.windows[0]) == "Thu 8:00–12:00"
    # #123, from the fourth live call: no budget on the phone, cash price first, the clinic's openings before our windows.
    with_budget = call_agent(spec.model_copy(update={"budget_max": 150, "insurance_carrier": "Delta Dental"}))
    for text in (prompt, with_budget):
        assert "$" not in text and "150" not in text, "the budget figure never reaches the prompt"
        assert "Never state or hint at the patient's budget" in text and "whether a price fits" in text
        assert text.index("1. Cash price") < text.index("2. Insurance") < text.index("3. Openings")
        assert "costs for a patient paying without insurance" in text
        assert "what appointment openings they have next week" in text
        assert text.index("what appointment openings they have next week") < text.index("Thu 8:00–12:00")
        assert "Do not mention the patient's free windows until the receptionist has named their openings" in text
    assert "whether the clinic accepts Delta Dental, and what a dental cleaning costs with it" in with_budget
    assert "go straight to question 3" in prompt and "go straight to question 3" not in with_budget


def test_build_messages_drops_vendor_system_prompt_and_keeps_order():
    spec = CallSpec(call_id="c", task_id="t", clinic_name="Oak Dental", care_type="dental cleaning", budget_max=150, insurance_carrier="Delta Dental")
    out = build_messages(spec, [{"role": "system", "content": "vendor"}, {"role": "user", "content": "hello"}, {"role": "assistant", "content": None}])
    assert [m["role"] for m in out] == ["system", "user", "assistant"]
    assert out[2]["content"] == ""
    assert "any time next week" in out[0]["content"]


def test_reasoning_deltas_are_stripped_before_relay():
    mixed = {
        "id": "x", "object": "chat.completion.chunk", "created": 1, "model": "m",
        "choices": [{"index": 0, "delta": {"reasoning": "the patient wants a cleaning", "reasoning_content": "...", "content": "Yes."}, "finish_reason": None}],
    }
    only_reasoning = {**mixed, "choices": [{"index": 0, "delta": {"reasoning_content": "thinking"}, "finish_reason": None}]}
    out = b"".join(relay(iter([only_reasoning, mixed, chunk("", "stop")])))
    sent = [json.loads(line[6:]) for line in out.decode().split("\n\n") if line.startswith("data: {")]
    assert all("reasoning" not in c["choices"][0]["delta"] and "reasoning_content" not in c["choices"][0]["delta"] for c in sent)
    assert "".join(delta_text(c) for c in sent) == "Yes."
    assert strip_reasoning(mixed)["choices"][0]["delta"] == {"content": "Yes."}
    assert strip_reasoning(chunk("hi")) == chunk("hi")
    assert b"thinking" not in out and b"patient wants" not in out


def test_relay_reports_first_token_and_full_sentence():
    seen = {}
    out = b"".join(relay(iter([chunk("Hel"), chunk("lo"), chunk("", "stop")]), on_first_token=lambda s: seen.setdefault("first", s), on_complete=lambda t: seen.setdefault("text", t)))
    assert out.endswith(b"data: [DONE]\n\n")
    assert seen["text"] == "Hello"
    assert seen["first"] >= 0


def test_lightning_client_streams_with_thinking_off(monkeypatch):
    from app.nemotron.call_agent import NO_THINK_EXTRA_BODY

    client = LightningClient(api_key="k", model_id="nvidia/x")
    seen = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return iter([])

    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    assert list(client.stream_chat([{"role": "user", "content": "hi"}])) == []
    assert seen["stream"] is True and seen["model"] == "nvidia/x"
    assert seen["extra_body"] == NO_THINK_EXTRA_BODY == {"chat_template_kwargs": {"enable_thinking": False}}


def test_lightning_client_never_guesses_a_model_id():
    with pytest.raises(ValueError, match="NEMOTRON_LIGHTNING_ID"):
        LightningClient(api_key="k", model_id="")
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        LightningClient(api_key="", model_id="nvidia/x")
    assert LightningClient(api_key="k", model_id="nvidia/x").model_id == "nvidia/x"


def test_proxy_without_a_client_and_without_a_model_id_fails_closed():
    app = create_app(load_settings(env_file=None, environ={k: v for k, v in ENV.items() if k != "NEMOTRON_LIGHTNING_ID"}))
    with TestClient(app) as c:
        with session_scope(app.state.engine) as s:
            s.add(Task(id="task-1", owner_id="mary", status="calling", intake_json="{}", windows_json="[]"))
            s.add(Call(id="call-a", task_id="task-1", clinic_name="Oak Dental", clinic_phone="+15555550113"))
        r = c.post("/v1/chat/completions", json=body())
        assert r.status_code == 503
        assert "NEMOTRON_LIGHTNING_ID" in r.json()["detail"]
