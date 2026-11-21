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

## Scenarios that wait on another PR

A test for a route or behaviour that is not merged yet is written to the contract in `docs/ARCHITECTURE.md` and marked
`xfail` with the issue number in the reason (T10 SMS NO → #23). When the PR merges the test turns `XPASS`; remove the marker in the same PR or the next refresh of
this folder, and update `RESULTS.md`.
