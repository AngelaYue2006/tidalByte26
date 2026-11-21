# Scenario tests

Cross-system tests T1–T12 from `docs/MVP.md` (Test matrix), run against the real FastAPI app with every adapter in mock
mode. One file per scenario in `scenarios/`, named after the matrix row (`T01_standard_run.py` … `T12_two_runs_reset.py`).
Actual outcomes, with the commit tested, are recorded in [`RESULTS.md`](RESULTS.md).

```
pytest -q tests/                      # schemas + every scenario
pytest -q tests/scenarios             # scenarios only
pytest -q tests/scenarios/T02_redaction.py
scripts/check.sh                      # runs them with the backend and integrations suites
```

## How it runs

- `scenarios/conftest.py` collects the `T<nn>_*.py` files (there is no pytest config in the repo and the names do not
  match `test_*.py` on purpose), puts `backend/` and the repo root on `sys.path`, and refuses every socket connection:
  a scenario that reaches the network fails.
- `scenarios/harness.py` builds the app the way `app.main.create_app` does, with only three substitutions: Nano and
  Super are stand-ins (`FakeNano`, `RecordingSuper`), the clock is pinned to Monday of the demo week, and every adapter
  is wrapped so a test can read what left the pipeline (`lab.outbound`, `lab.sms`, `lab.calendar_writes`).
  `ScenarioVoice` replays `backend/fixtures/receptionists.json` exactly like the app's mock voice path and lets one
  scenario override a clinic's offer or booking reply (T4, T5, T7) or hold a call open mid-transcript (T11).
- Each test drives the app through its REST routes and reads back `GET /api/tasks/{id}`, `GET /api/tasks/{id}/events`
  for both viewer roles and the `GET /api/live` snapshot, validating against `shared/*.schema.json`.

## Scenarios and unmerged work

A test for a route or behaviour that is not merged yet is written to the contract in `docs/ARCHITECTURE.md` and marked
`xfail` with the issue number in the reason; when the PR merges the test turns `XPASS`, and the marker comes off in the
next refresh of this folder together with `RESULTS.md`. As of main `6441ed5` nothing is marked: T10's SMS decline was the
last one and passes since #23 merged.

## What the webhook scenarios exercise

- **Twilio SMS (T6, T8, T9, T10):** `Lab.twilio_sms` posts the form Twilio would post, with no `X-Twilio-Signature`.
  `SMS_MODE=mock` means `integrations.sms_twilio.parse_inbound` verifies the sender against the fixture people and the
  allowlist, not a signature, so these scenarios cover form handling, allowlist, MessageSid replay and the YES/NO
  branches; the live signature check is #27's and is tested there.
- **ElevenLabs post-call (T8):** `Lab.post_call_webhook` signs the replayed payload with `ELEVENLABS_WEBHOOK_SECRET`
  the way ElevenLabs does, so the signed path is exercised.
- **No socket leaves the process.** `conftest.py` replaces `socket.connect` for every scenario. The one connect allowed
  is to a loopback port this process bound itself, which is how asyncio on Windows builds its wake-up socketpair;
  anything else on the machine, Ollama on `localhost:11434` included, is refused.
