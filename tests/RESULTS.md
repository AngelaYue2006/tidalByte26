# Scenario results

**Commit tested:** `5c3f78e` on `main` (backend with receipts, history and demo reset from #24, integrations, shared and fixtures as merged on 2026-11-21).
**Command:** `pytest -q tests/` from the repo root in the shared venv; `scripts/check.sh` ran the same files with the
backend and integrations suites. Every adapter in mock mode; no socket left the process.

**Summary:** 50 passed, 4 xfailed (19 scenario tests passed, 4 wait on unmerged PRs). Pass means the scenario's
expected result from `docs/MVP.md` holds; xfail means the behaviour belongs to a PR that has not merged, and the test is
written to the documented contract so it turns green when it does.

| ID | Scenario | Test | Result | Note |
|---|---|---|---|---|
| T1 | Standard run | `T01_standard_run.py` (3 tests) | pass | Bright Smile picked, one approval, booked once, calendar once, no accessible ride, Sarah drives, `completed`; same trail for the contact without the raw request |
| T2 | Raw request with symptoms and member ID | `T02_redaction.py` (2 tests) | pass | Chips, intake, contact view, every cloud-bound payload, every SMS, the INFO log and `metrics.jsonl` carry none of the dropped values; a leaking Nano proposal fails closed before any cloud call |
| T3 | All three offers over budget | `T03_all_over_budget.py` | pass | `failed` with `NO_ELIGIBLE_OFFER`; one honest message naming every clinic and price, visible to both roles; Super never called |
| T4 | Offer outside free windows | `T04_outside_windows.py` (2 tests) | pass | Smile Co. and Oak Dental `slotOk: false` on the card and the snapshot; only Bright Smile reaches Super; moving an offer into a window makes it eligible |
| T5 | Clinic does not take the insurance | `T05_not_insured.py` | pass | Bright Smile `insured: false` on the card, never ranked; Smile Co. wins and is the one booked |
| T6 | Owner does not approve within the timeout | `T06_approval_timeout.py` | pass / xfail | Nothing booked while waiting, one SMS (the pick), approval still works later: pass. With `Pipeline.approval_timeout_s` shortened, one reminder SMS and an `APPROVAL_TIMEOUT` event while the task keeps waiting: xfail, #22 (PR #80) |
| T7 | Clinic says "we'll call back to confirm" | `T07_tentative_booking.py` (2 tests) | pass | `booked` with `tentative: true`, empty calendar text, no calendar write, booking `calendar_event_id: null`; a rejected confirmation fails the task with `BOOKING_REJECTED` |
| T8 | Repeated Twilio webhook | `T08_duplicate_webhook.py` | pass / xfail | Request, approval and contact-offer keys replay once each through the receipts table (#24); a repeated ElevenLabs post-call webhook adds no event: pass. A repeated Twilio `YES` answered 200 with TwiML and booking once: xfail, #22 (PR #80) |
| T9 | Reply from a number not on the allowlist | `T09_unknown_sender.py` | pass / xfail | A viewer outside owner and contact gets 404s, an empty history and an empty snapshot: pass. Inbound SMS from an unknown number answered 200 with empty TwiML (Twilio retries anything else), no task data in the reply, logged without the sender's number: xfail, #22 (PR #80) |
| T10 | Contact declines | `T10_contact_declines.py` | pass / xfail | Dashboard decline keeps `awaiting_contact`, the owner sees `contact_reply`, no `ride_confirmed`; a later offer completes once: pass. SMS `NO` adds `contact_reply` plus an owner-only `CONTACT_DECLINED` note and keeps waiting, a later `YES` confirms once: xfail, #23 (PR #81) |
| T11 | Dashboard refresh mid-call | `T11_refresh_snapshot.py` | pass | Snapshot mid-call restores two finished cards, the live card and its transcripts; the reconnect sends only ids above the snapshot cursor; snapshot plus stream equals the persisted trail once |
| T12 | Two runs then reset | `T12_two_runs_reset.py` (2 tests) | pass | Two full runs, both `completed`, history newest first for both roles, no shared ids or receipts. `POST /api/demo/reset` stops pipelines, wipes every table, reseeds the contact and two simulated past runs (old ids answer 404, the snapshot shows the newest seeded run), a third run completes; 403 outside development |

Refresh this file after #80 and #81 merge: run `pytest -q tests/ -rA`, remove the `xfail` markers that turned `XPASS`,
and update the commit, summary and the four `pass / xfail` rows.
