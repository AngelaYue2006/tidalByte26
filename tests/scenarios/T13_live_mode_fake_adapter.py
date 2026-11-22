"""T13 — Live-mode run with a fake ElevenLabs adapter: start_call ×3, post-call webhooks, full trail to completed."""

from __future__ import annotations

import time

from harness import (
    BRIGHT,
    DEMO_NOW,
    DEMO_TEXT,
    LIVE_COLLECTIONS,
    OAK,
    PROXY_SECRET,
    SMILE,
    Lab,
    LiveScenarioVoice,
    make_live_lab,
)

STATUS_TRAIL = ["intake", "calendar", "places", "calling", "ranking", "awaiting_approval", "booking", "transport", "awaiting_contact", "completed"]


def _wait_live_calls(lab: Lab, task_id: str, n: int = 3, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        voice = lab.voice
        assert isinstance(voice, LiveScenarioVoice)
        if len(voice.starts) >= n:
            return
        time.sleep(0.02)
    raise AssertionError(f"expected {n} start_call invocations; got {len(lab.voice.starts)}")


def _post_results(lab: Lab, task_id: str) -> None:
    ids = lab.call_ids(task_id)
    for clinic, call_id in ids.items():
        payload = {
            "type": "post_call_transcription",
            "event_timestamp": int(DEMO_NOW.timestamp()),
            "data": {
                "agent_id": "agent-x",
                "conversation_id": f"conv-{call_id}",
                "status": "done",
                "transcript": [
                    {"role": "agent", "message": "Hi, I'm an AI assistant calling for a patient.", "time_in_call_secs": 1},
                    {"role": "user", "message": "We can help with that.", "time_in_call_secs": 3},
                ],
                "analysis": {"data_collection_results": LIVE_COLLECTIONS[clinic], "call_successful": "success"},
                "conversation_initiation_client_data": {"dynamic_variables": {"call_id": call_id}},
            },
        }
        r = lab.post_call_webhook(payload)
        assert r.status_code == 200, r.text
        assert r.json()["duplicate"] is False and r.json().get("complete") is True


def test_t13_live_mode_fake_adapter_reaches_completed(lab_factory, monkeypatch, tmp_path):
    lab = make_live_lab(monkeypatch, tmp_path / "t13")
    try:
        task_id = lab.start(DEMO_TEXT)
        _wait_live_calls(lab, task_id)
        voice = lab.voice
        assert isinstance(voice, LiveScenarioVoice)
        assert len(voice.starts) == 3
        assert {s["call_id"] for s in voice.starts} == set(lab.call_ids(task_id).values())
        assert all(s["proxy_secret"] == PROXY_SECRET for s in voice.starts)
        assert all(s.call_id for s in voice.specs)

        starts = [o for o in lab.outbound if o.target == "voice.start_call"]
        assert len(starts) == 3
        assert not any(o.target == "voice.call_clinics" for o in lab.outbound)

        _post_results(lab, task_id)
        task = lab.wait_for(task_id, "awaiting_approval", timeout=8.0)
        assert task["decision"]["winner_call_id"]

        live_statuses = [e for e in lab.events(task_id) if e["type"] == "call_status" and e.get("status") == "live"]
        assert len(live_statuses) == 3 and all(e.get("simulated") is False for e in live_statuses)
        assert len(lab.of_type(task_id, "call_result")) == 3

        assert lab.approve(task_id).json()["applied"] is True
        lab.wait_for(task_id, "awaiting_contact")
        assert lab.offer(task_id, can_drive=True).json()["status"] == "ride_confirmed"
        task = lab.wait_for(task_id, "completed")

        assert [e["status"] for e in lab.of_type(task_id, "task_updated")] == STATUS_TRAIL
        assert task["booking"]["clinic"] == BRIGHT and task["booking"]["status"] == "confirmed"
        assert voice.confirmed == [lab.call_ids(task_id)[BRIGHT]]
        assert set(lab.call_ids(task_id)) == {BRIGHT, SMILE, OAK}
        lab.validate_trail(task_id)
    finally:
        lab.close()
