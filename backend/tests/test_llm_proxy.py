"""Issue #20: the custom-LLM proxy checks the secret, finds the call, builds the redacted prompt, relays Lightning's stream and logs turns."""

import json
from datetime import UTC, datetime

import pytest
from app.config import load_settings
from app.db import session_scope
from app.main import create_app
from app.models import Call, Task, Turn
from app.nemotron.call_agent import LightningClient, build_messages, delta_text, relay
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
        (1, "clinic", "Yes, we do. A cleaning is $95 with Delta."),
        (2, "agent", "Yes. Do you take Delta Dental?"),
    ]


def test_resent_conversation_does_not_duplicate_the_clinic_turn(client, app):
    client.post("/v1/chat/completions", json=body())
    client.post("/v1/chat/completions", json=body())  # ElevenLabs retry with the same history and the same reply
    assert [t[1] for t in turns(app)] == ["clinic", "agent"]
    app.state.lightning_client.pieces = ["Thursday ", "works."]
    client.post("/v1/chat/completions", json=body(messages=body()["messages"] + [
        {"role": "assistant", "content": "Yes. Do you take Delta Dental?"},
        {"role": "user", "content": "Thursday at 9:30 is open."},
    ]))
    assert [t[1:] for t in turns(app)] == [
        ("clinic", "Yes, we do. A cleaning is $95 with Delta."),
        ("agent", "Yes. Do you take Delta Dental?"),
        ("clinic", "Thursday at 9:30 is open."),
        ("agent", "Thursday works."),
    ]


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
    for fact in ("Bright Smile Dental", "dental cleaning", "$150", "Delta Dental", "Tue 1:00–5:00", "Thu 8:00–12:00"):
        assert fact in system
    serialised = json.dumps(messages)
    for secret in ("DEMO-0000", "knee", "Mary", "member_id", "ElevenLabs default agent prompt", "elevenlabs_extra_body", PROXY_SECRET):
        assert secret not in serialised
    assert [m["role"] for m in messages] == ["system", "assistant", "user"]
    assert RAW_UTTERANCE not in serialised


def test_prompt_discloses_ai_and_never_books():
    spec = CallSpec(call_id="c", task_id="t", clinic_name="Oak Dental", care_type="dental cleaning", windows=[(datetime(2026, 11, 26, 8, tzinfo=UTC), datetime(2026, 11, 26, 12, tzinfo=UTC))])
    prompt = call_agent(spec)
    assert prompt.count(OPENING_LINE) == 1
    assert "You are an AI" in prompt
    assert "Never book" in prompt
    assert "no insurance to mention" in prompt
    assert "budget" not in prompt.lower().replace("the patient's budget", "")  # no budget line when None
    assert window_label(*spec.windows[0]) == "Thu 8:00–12:00"


def test_build_messages_drops_vendor_system_prompt_and_keeps_order():
    spec = CallSpec(call_id="c", task_id="t", clinic_name="Oak Dental", care_type="dental cleaning", budget_max=150, insurance_carrier="Delta Dental")
    out = build_messages(spec, [{"role": "system", "content": "vendor"}, {"role": "user", "content": "hello"}, {"role": "assistant", "content": None}])
    assert [m["role"] for m in out] == ["system", "user", "assistant"]
    assert out[2]["content"] == ""
    assert "any time this week" in out[0]["content"]


def test_relay_reports_first_token_and_full_sentence():
    seen = {}
    out = b"".join(relay(iter([chunk("Hel"), chunk("lo"), chunk("", "stop")]), on_first_token=lambda s: seen.setdefault("first", s), on_complete=lambda t: seen.setdefault("text", t)))
    assert out.endswith(b"data: [DONE]\n\n")
    assert seen["text"] == "Hello"
    assert seen["first"] >= 0


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
