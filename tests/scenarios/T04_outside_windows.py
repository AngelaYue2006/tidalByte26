"""T4 — Offer outside the free windows: removed by the hard rules before ranking; shown in red on the card (`slotOk: false`)."""

from __future__ import annotations

from datetime import datetime

from harness import BRIGHT, CHICAGO, OAK, SMILE, Lab, ScenarioVoice

THU_1030 = datetime(2026, 11, 26, 10, 30, tzinfo=CHICAGO)  # inside Mary's Thu am window (08:00–12:00)


def test_t4_offers_outside_the_windows_are_red_on_the_card_and_never_reach_super(lab: Lab):
    task_id = lab.start()
    task = lab.wait_for(task_id, "awaiting_approval")
    ids = lab.call_ids(task_id)
    results = {e["call_id"]: e for e in lab.of_type(task_id, "call_result")}
    # Smile Co. (Fri 4:00) and Oak Dental (Mon 10:00) fall outside Tue pm and Thu am
    assert results[ids[SMILE]]["slotOk"] is False and results[ids[OAK]]["slotOk"] is False
    assert results[ids[BRIGHT]]["slotOk"] is True
    # the ranker was given the survivor only, and the decision ranks only what it was given
    assert lab.ranker.offers_seen == [[ids[BRIGHT]]]
    assert [r["call_id"] for r in task["decision"]["ranked"]] == [ids[BRIGHT]]
    assert task["decision"]["winner_call_id"] == ids[BRIGHT]
    # the dashboard cards carry the same verdict after a refresh
    _, snap = lab.snapshot()
    cards = {c["clinic"]: c["result"] for c in snap["calls"]}
    assert cards[SMILE]["slotOk"] is False and cards[OAK]["slotOk"] is False and cards[BRIGHT]["slotOk"] is True


def test_t4_an_offer_moved_into_a_window_becomes_eligible(lab_factory):
    """The filter is the window check, not the clinic: Oak Dental inside Thu am and cheaper wins; Smile Co. stays out."""
    voice = ScenarioVoice(offer_overrides={OAK: {"slot_start": THU_1030, "slot_end": THU_1030.replace(hour=11), "price": 90}})
    lab: Lab = lab_factory(voice=voice)
    task_id = lab.start()
    task = lab.wait_for(task_id, "awaiting_approval")
    ids = lab.call_ids(task_id)
    results = {e["call_id"]: e for e in lab.of_type(task_id, "call_result")}
    assert results[ids[OAK]] == {**results[ids[OAK]], "price": "$90", "slot": "Thu 10:30", "slotOk": True}
    assert results[ids[SMILE]]["slotOk"] is False
    assert sorted(lab.ranker.offers_seen[0]) == sorted([ids[BRIGHT], ids[OAK]])
    assert task["decision"]["winner_call_id"] == ids[OAK]
    assert lab.of_type(task_id, "decision")[0]["title"] == f"Why Nemotron picked {OAK}"
