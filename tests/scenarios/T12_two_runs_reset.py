"""T12 — Two runs then reset: history shows both; `POST /api/demo/reset` clears and reseeds."""

from __future__ import annotations

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


def test_t12_reset_clears_the_runs_reseeds_two_past_runs_and_a_third_run_works(lab_factory):
    lab: Lab = lab_factory()
    first = full_run(lab)
    second = full_run(lab)

    r = lab.reset()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stopped"] == 0 and body["seeded"] == {"tasks": 2, "contacts": 1}
    assert body["cleared"]["tasks"] == 2 and body["cleared"]["calls"] == 6 and body["cleared"]["receipts"] > 0
    for old in (first, second):
        assert lab.client.get(f"/api/tasks/{old}?viewer_id=mary").status_code == 404, "the runs are gone"
        assert lab.client.get(f"/api/tasks/{old}/events?viewer_id=mary").status_code == 404

    # the history page shows the two seeded past runs, newest first, finished and simulated
    seeded = lab.history(owner_id="mary")
    assert len(seeded) == 2 and all(t["status"] == "completed" for t in seeded)
    assert seeded[0]["created_at"] > seeded[1]["created_at"]
    assert all(t["id"] not in (first, second) for t in seeded)
    assert [t["id"] for t in lab.history(CONTACT, owner_id="mary")] == [t["id"] for t in seeded], "the contact row was reseeded"
    assert all("request_text" not in t for t in lab.history(CONTACT, owner_id="mary"))
    for task in seeded:
        assert all(e.get("simulated", True) for e in lab.events(task["id"]) if e["type"] in ("call_result", "transport_check", "booked"))
        lab.validate_trail(task["id"])
    _, snap = lab.snapshot()
    assert snap["task"]["id"] == seeded[0]["id"], "a refresh after reset shows the newest seeded run"

    # the demo runs again from the reseeded state
    third = full_run(lab)
    history = lab.history(owner_id="mary")
    assert history[0]["id"] == third and len(history) == 3
    assert lab.reset().json()["cleared"]["tasks"] == 3

    # reset is a development-only switch
    other = lab_factory(env={"APP_ENV": "staging", "DASHBOARD_SESSION_SECRET": "scenario-session-secret-0123456789"})
    assert other.reset().status_code == 403 and other.history(owner_id="mary") == [], "nothing seeded outside development"
