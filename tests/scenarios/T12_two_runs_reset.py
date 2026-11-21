"""T12 — Two runs then reset: history shows both; `POST /api/demo/reset` clears and reseeds."""

from __future__ import annotations

import pytest
from harness import CONTACT, CONTACT_PHONE, OWNER_PHONE, Lab


def full_run(lab: Lab) -> str:
    task_id = lab.start()
    lab.wait_for(task_id, "awaiting_approval")
    lab.approve(task_id)
    lab.wait_for(task_id, "awaiting_contact")
    lab.offer(task_id, can_drive=True)
    lab.wait_for(task_id, "completed")
    return task_id


def test_t12_two_runs_in_a_row_both_complete_and_both_show_in_history(lab: Lab):
    first = full_run(lab)
    second = full_run(lab)
    assert first != second

    history = lab.history(owner_id="mary")
    assert [t["id"] for t in history] == [second, first], "newest first"
    assert all(t["status"] == "completed" and t["booking"]["status"] == "confirmed" for t in history)
    contact_history = lab.history(CONTACT, owner_id="mary")
    assert [t["id"] for t in contact_history] == [second, first] and all("request_text" not in t for t in contact_history)

    # the runs never share a call id, an event or a receipt
    assert not set(lab.call_ids(first).values()) & set(lab.call_ids(second).values())
    assert not {e["id"] for e in lab.events(first)} & {e["id"] for e in lab.events(second)}
    assert lab.calendar_writes == [f"{first}:calendar", f"{second}:calendar"]
    assert len(lab.sms_to(OWNER_PHONE)) == 6 and len(lab.sms_to(CONTACT_PHONE)) == 4
    _, snap = lab.snapshot()
    assert snap["task"]["id"] == second and snap["task"]["status"] == "completed"
    lab.validate_trail(first)
    lab.validate_trail(second)


@pytest.mark.xfail(reason="#24 (PR #82): POST /api/demo/reset is not merged yet", strict=False)
def test_t12_reset_clears_the_runs_and_reseeds_so_a_third_run_works(lab_factory):
    lab: Lab = lab_factory()
    first = full_run(lab)
    full_run(lab)

    r = lab.reset()
    assert r.status_code == 200, r.text
    assert lab.history(owner_id="mary") == []
    assert lab.client.get(f"/api/tasks/{first}?viewer_id=mary").status_code == 404
    _, snap = lab.snapshot()
    assert snap["task"] is None and snap["events"] == []

    third = full_run(lab)  # the fixtures are back: owner, contact, clinics, windows
    assert [t["id"] for t in lab.history(owner_id="mary")] == [third]
    assert [t["id"] for t in lab.history(CONTACT, owner_id="mary")] == [third], "the contact row was reseeded"

    # reset is a development-only switch
    other = lab_factory(env={"APP_ENV": "staging", "DASHBOARD_SESSION_SECRET": "scenario-session-secret-0123456789"})
    assert other.reset().status_code in (403, 404)
