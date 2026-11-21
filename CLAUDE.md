# LifeLine — instructions for coding agents

> Interim version. Joyce will supply a CLAUDE.md template; this file will be rewritten to it. Until then, follow this.

## What this is
LifeLine: an older adult (or their emergency contact) speaks a request on a dashboard; a local Nemotron Nano redacts it; three AI agents phone three clinics in parallel; Nemotron Super ranks the offers and explains the pick; the user approves once; LifeLine books, adds a calendar event, checks for a ride and texts the emergency contact when none is accessible. Hackathon build, three people, tracks: NVIDIA Nemotron (main), ElevenLabs, overall.

## Read before writing code
1. `docs/DECISIONS.md` — every decision and why. Do not reopen a decided item; propose a change in a PR instead.
2. `docs/ARCHITECTURE.md` — pipeline, data model, REST + SSE contract, adapter signatures, env vars.
3. `docs/MVP.md` — acceptance criteria, team split, test matrix, cut list.
4. `AGENTS.md` — ownership and PR rules.

## Hard rules
- Only call phones listed in `DEMO_PHONE_ALLOWLIST`. Never a real clinic. The agent always says it is an AI.
- The raw utterance never leaves the device. Only the redacted `IntakeRequest` goes to the cloud.
- No booking or calendar write before an `approved` event. One approval, never more questions than that.
- Status comes from structured results and receipts, never from transcript text.
- Text transcripts only. No audio stored.
- Every adapter has a mock mode that emits the same events. Build against mocks first.
- Never commit `.env`, tokens, phone numbers or real personal data. Fixtures are synthetic.

## Working in this repo
- Stay in your owner's folder (`backend/`, `integrations/`, `frontend/`). `shared/` and `docs/ARCHITECTURE.md` change only by reviewed PR.
- The dashboard event names in `docs/ARCHITECTURE.md` are the contract; `frontend/prototype/index.html` shows how each renders.
- Small PRs. Say what you tested and how. Mark anything mocked as mocked.
- Model IDs come from `.env`. Do not hard-code or guess them.
