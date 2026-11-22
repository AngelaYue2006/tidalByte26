"""T3 — All three offers over budget: no pick; task `failed` with a reason; owner and contact told honestly."""

from __future__ import annotations

from harness import BRIGHT, CONTACT, DEMO_TEXT, OAK, SMILE, Lab

OVER_BUDGET_TEXT = DEMO_TEXT.replace("$150", "$50")  # the on-device backstop reads the cap from the words


def test_t3_nothing_fits_the_budget_fails_with_an_honest_message(lab: Lab):
    task_id = lab.start(OVER_BUDGET_TEXT)
    task = lab.wait_for(task_id, "failed")

    assert task["chips"][1] == "Max $50"
    assert task["failure_reason"] == "NO_ELIGIBLE_OFFER" and task["decision"] is None and task["booking"] is None
    # the hard rules ran in code: Super never saw an offer, nothing was approved, booked or written to the calendar
    assert lab.ranker.prompts == [] and lab.voice.confirmed == [] and lab.calendar_writes == []
    types = lab.types(task_id)
    assert types.count("call_result") == 3, "every clinic answered; none fit"
    assert not {"decision", "approval_required", "approved", "booked", "notified", "contact_request"} & set(types)
    assert [e["status"] for e in lab.of_type(task_id, "task_updated")] == ["intake", "calendar", "places", "calling", "ranking", "failed"]

    failure = lab.of_type(task_id, "task_updated")[-1]
    assert failure["reason"] == "NO_ELIGIBLE_OFFER" and "nothing was booked" in failure["message"]
    for clinic, price in ((BRIGHT, "$95"), (SMILE, "$120"), (OAK, "$140")):
        assert f"{clinic}: {price} is over the $50 budget" in failure["message"]

    # both roles see the same honest failure; neither sees a pick
    contact_failure = lab.of_type(task_id, "task_updated", CONTACT)[-1]
    assert contact_failure["message"] == failure["message"] and contact_failure["reason"] == "NO_ELIGIBLE_OFFER"
    assert lab.task(task_id, CONTACT)["failure_reason"] == "NO_ELIGIBLE_OFFER"
    assert "decision" not in lab.types(task_id, CONTACT)
    lab.validate_trail(task_id)
