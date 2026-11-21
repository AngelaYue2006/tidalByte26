"""T5 — Clinic does not take the insurance: removed by the hard rules; the card shows Insurance: No (`insured: false`)."""

from __future__ import annotations

from datetime import datetime

from harness import BRIGHT, CHICAGO, OAK, SMILE, Lab, ScenarioVoice

THU_1030 = datetime(2026, 11, 26, 10, 30, tzinfo=CHICAGO)


def test_t5_uninsured_clinic_shows_insurance_no_and_is_not_ranked(lab_factory):
    # Bright Smile stops taking Delta Dental; Smile Co. opens a slot inside Thu am so one offer still fits.
    voice = ScenarioVoice(offer_overrides={
        BRIGHT: {"insured": False},
        SMILE: {"slot_start": THU_1030, "slot_end": THU_1030.replace(hour=11)},
    })
    lab: Lab = lab_factory(voice=voice)
    task_id = lab.start()
    task = lab.wait_for(task_id, "awaiting_approval")
    ids = lab.call_ids(task_id)
    results = {e["call_id"]: e for e in lab.of_type(task_id, "call_result")}

    assert results[ids[BRIGHT]]["insured"] is False and results[ids[BRIGHT]]["slotOk"] is True, "the card says Insurance: No"
    assert results[ids[SMILE]]["insured"] is True and results[ids[SMILE]]["slotOk"] is True
    assert lab.ranker.offers_seen == [[ids[SMILE]]], "Super never saw the uninsured offer"
    assert task["decision"]["winner_call_id"] == ids[SMILE]
    decision = lab.of_type(task_id, "decision")[0]
    assert decision["title"] == f"Why Nemotron picked {SMILE}" and "Takes Delta Dental" in decision["reasons"]
    _, snap = lab.snapshot()
    assert next(c for c in snap["calls"] if c["clinic"] == BRIGHT)["result"]["insured"] is False

    # the booking goes to the clinic that takes the insurance
    lab.approve(task_id)
    task = lab.wait_for(task_id, "awaiting_contact")
    assert task["booking"]["clinic"] == SMILE and lab.voice.confirmed == [ids[SMILE]]
    assert OAK not in str(task["booking"]) and BRIGHT not in str(task["booking"])
    lab.validate_trail(task_id)
