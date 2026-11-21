# Scenario results

**Commit tested:** `e86ae59` on `main` (backend, integrations, shared and fixtures as merged on 2026-11-21).
**Command:** `pytest -q tests/` from the repo root in the shared venv; `scripts/check.sh` ran the same files with the
backend and integrations suites. Every adapter in mock mode; no socket left the process.

**Summary:** 49 passed, 5 xfailed (18 scenario tests passed, 5 wait on unmerged PRs). Pass means the scenario's
expected result from `docs/MVP.md` holds; xfail means the behaviour belongs to a PR that has not merged, and the test is
written to the documented contract so it turns green when it does.

| ID | Scenario | Test | Result | Note |
|---|---|---|---|---|
| T1 | Standard run | `T01_standard_run.py` (3 tests) | pass | Bright Smile picked, one approval, booked once, calendar once, no accessible ride, Sarah drives, `completed`; same trail for the contact without the raw request |
| T2 | Raw request with symptoms and member ID | `T02_redaction.py` (2 tests) | pass | Chips, intake, contact view, every cloud-bound payload, every SMS, the INFO log and `metrics.jsonl` carry none of the dropped values; a leaking Nano proposal fails closed before any cloud call |
| T3 | All three offers over budget | `T03_all_over_budget.py` | pass | `failed` with `NO_ELIGIBLE_OFFER`; one honest message naming every clinic and price, visible to both roles; Super never called |
| T4 | Offer outside free windows | `T04_outside_windows.py` (2 tests) | pass | Smile Co. and Oak Dental `slotOk: false` on the card and the snapshot; only Bright Smile reaches Super; moving an offer into a window makes it eligible |
| T5 | Clinic does not take the insurance | `T05_not_insured.py` | pass | Bright Smile `insured: false` on the card, never ranked; Smile Co. wins and is the one booked |
| T6 | Owner does not approve within the timeout | `T06_approval_timeout.py` | pass / xfail | Nothing booked while waiting, one SMS (the pick), approval still works later: pass. One reminder SMS and an `APPROVAL_TIMEOUT` event: xfail, #22 (PR #80) |
| T7 | Clinic says "we'll call back to confirm" | `T07_tentative_booking.py` (2 tests) | pass | `booked` with `tentative: true`, empty calendar text, no calendar write, booking `calendar_event_id: null`; a rejected confirmation fails the task with `BOOKING_REJECTED` |
| T8 | Repeated Twilio webhook | `T08_duplicate_webhook.py` | pass / xfail | Request, approval and contact-offer keys replay once each; a repeated ElevenLabs post-call webhook adds no event: pass. A repeated Twilio `YES` books once: xfail, #22 (PR #80) |
| T9 | Reply from a number not on the allowlist | `T09_unknown_sender.py` | pass / xfail | A viewer outside owner and contact gets 404s, an empty history and an empty snapshot: pass. Inbound SMS from an unknown number rejected and logged as `UNVERIFIED_SENDER`: xfail, #22 (PR #80) |
| T10 | Contact declines | `T10_contact_declines.py` | pass / xfail | Dashboard decline keeps `awaiting_contact`, the owner sees `contact_reply`, no `ride_confirmed`; a later offer completes once: pass. SMS `NO` then `YES`: xfail, #23 (PR #81) |
| T11 | Dashboard refresh mid-call | `T11_refresh_snapshot.py` | pass | Snapshot mid-call restores two finished cards, the live card and its transcripts; the reconnect sends only ids above the snapshot cursor; snapshot plus stream equals the persisted trail once |
| T12 | Two runs then reset | `T12_two_runs_reset.py` | pass / xfail | Two full runs, both `completed`, history newest first for both roles, no shared ids or receipts: pass. `POST /api/demo/reset` clears and reseeds: xfail, #24 (PR #82) |

Refresh this file after the three PRs merge: run `pytest -q tests/ -rA`, remove the `xfail` markers that turned `XPASS`,
and update the commit, summary and the four `pass / xfail` rows.
