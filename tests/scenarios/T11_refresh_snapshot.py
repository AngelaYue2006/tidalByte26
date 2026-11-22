"""T11 — Dashboard refresh mid-call: the snapshot restores the cards and transcripts; nothing is sent twice."""

from __future__ import annotations

from harness import (
    BRIGHT,
    CONTACT,
    DEMO_TEXT,
    OAK,
    SMILE,
    Gate,
    Lab,
    ScenarioVoice,
    until,
)


def test_t11_refresh_mid_call_restores_cards_and_transcripts_without_duplicates(lab_factory):
    gate = Gate(BRIGHT, after_lines=2)  # Bright Smile's call pauses after its second transcript line
    lab: Lab = lab_factory(voice=ScenarioVoice(gate=gate))
    task_id = lab.start()
    assert gate.reached.wait(5), "the call never paused"
    lab.settle(0.2)  # the other two calls run instantly to `done`

    # the first tab: what the dashboard had before the refresh
    first_id, first = lab.snapshot()
    assert first["task"]["status"] == "calling"
    cards = {c["clinic"]: c for c in first["calls"]}
    assert cards[BRIGHT]["status"] == "live" and cards[BRIGHT]["result"] is None
    assert cards[SMILE]["status"] == "done" and cards[SMILE]["result"]["price"] == "$120"
    assert cards[OAK]["status"] == "done" and cards[OAK]["result"]["price"] == "$140"
    ids = lab.call_ids(task_id)
    transcripts = [e for e in first["events"] if e["type"] == "transcript"]
    assert sum(e["call_id"] == ids[BRIGHT] for e in transcripts) == 2 and sum(e["call_id"] == ids[OAK] for e in transcripts) >= 2
    assert sum(e["type"] == "call_start" for e in first["events"]) == 3
    first_ids = [e["id"] for e in first["events"]]
    assert len(set(first_ids)) == len(first_ids) and max(first_ids) == first_id, "the snapshot carries the id of its last event"
    # the contact's refresh mid-call: same cards and transcripts, never the raw request
    _, contact_snap = lab.snapshot(CONTACT)
    assert [c["status"] for c in contact_snap["calls"]] == [c["status"] for c in first["calls"]]
    assert sum(e["type"] == "transcript" for e in contact_snap["events"]) == len(transcripts)
    assert "request_text" not in contact_snap["task"] and DEMO_TEXT not in str(contact_snap)

    # the refresh: a new connection gets the same state back, then only what happens next
    with lab.stream() as messages:
        snap_id, snap = next(messages)
        assert snap["type"] == "snapshot" and [e["id"] for e in snap["events"]] == first_ids and snap_id == first_id
        gate.released.set()
        streamed: list[dict] = []
        while True:
            event_id, message = until(messages, lambda m: m[1]["type"] != "heartbeat")
            streamed.append(message)
            assert event_id == message["id"] > snap_id
            if message["type"] == "task_updated" and message["status"] == "awaiting_approval":
                break
    streamed_ids = [e["id"] for e in streamed]
    assert not set(streamed_ids) & set(first_ids), "nothing in the snapshot is sent again"
    assert streamed_ids == sorted(streamed_ids) and len(set(streamed_ids)) == len(streamed_ids)
    bright_after = [e for e in streamed if e["type"] == "transcript" and e["call_id"] == ids[BRIGHT]]
    assert bright_after, "the rest of Bright Smile's transcript arrived on the stream"
    assert {e["type"] for e in streamed} >= {"transcript", "call_result", "call_status", "decision"}

    # snapshot plus stream is exactly the persisted trail up to that point, once each
    persisted = [e["id"] for e in lab.events(task_id) if e["id"] <= max(streamed_ids)]
    assert first_ids + streamed_ids == persisted
    cards_after = {c["clinic"]: c for c in lab.snapshot()[1]["calls"]}
    assert cards_after[BRIGHT]["status"] == "done" and cards_after[BRIGHT]["result"]["price"] == "$95"
