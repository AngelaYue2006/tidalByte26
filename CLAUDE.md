# CLAUDE.md

Guidance for Claude Code working in this repository.

GranniAI is a hackathon build: an older adult (or their emergency contact) speaks a request on a dashboard, a local Nemotron Nano redacts it, three AI agents phone three clinics in parallel, Nemotron Super ranks the offers and explains the pick, the user approves once, and GranniAI books, adds a calendar event, checks for a ride and texts the emergency contact when none is accessible. **Several AI sessions run at once under three GitHub accounts** (Joyce, Angela, Michael), so a session cannot tell its own past actions from another's — take your own worktree, and trust repository state over any summary.

## Before you write code

- **[`docs/DECISIONS.md`](docs/DECISIONS.md)** — every design decision and why. Required. Do not reopen a decided item; propose a change in a PR that also edits the doc.
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — the system map: pipeline, data model, REST and SSE contracts, adapter signatures, env vars. The event list there is the dashboard contract.
- **[`docs/MVP.md`](docs/MVP.md)** — acceptance criteria, team split, gates, test matrix T1–T12, cut list.
- **[`AGENTS.md`](AGENTS.md)** — who owns which folder, roles, the issue-to-PR flow.
- Your issue. Its acceptance list is what "done" means. Take the open issue assigned to your person with the lowest gate number, unless an owner names other work.

**The docs describe intent; the code is the fact.** Never assume a documented endpoint or adapter exists — check. Every skeleton file has a one-line header saying what belongs in it and nothing else yet. **Never infer a requirement from the prototype, a fixture, a demo script, or Git history.** `frontend/prototype/index.html` is the visual spec for how events render, not a source of requirements; the LifeLine v0 docs at commit `f09f0a7` and the Slotted plan in `docs/archive/` are superseded on purpose.

**A later explicit owner decision beats this file and the docs.** Update the contradicted text in the same PR; never leave two versions of a rule alive.

## Commands

```
scripts/check.sh                               # ruff + pytest + frontend lint/tsc — run before every push
cd backend && uvicorn app.main:app --reload     # localhost:8000
cd backend && pytest -q                        # backend tests
pytest -q tests/                               # scenario tests T1–T12 against the mock backend
pytest -q backend/tests/test_intake_redaction.py -k dropped   # one test
cd frontend && npm install && npm run dev      # localhost:3000; /api/* is rewritten to :8000
cd frontend && npm run lint && npx tsc --noEmit
ollama run $NEMOTRON_NANO_TAG                  # local intake model must be running
ngrok http 8000                                # PUBLIC_BASE_URL for Twilio and ElevenLabs webhooks
curl -X POST localhost:8000/api/demo/reset     # clear and reseed between runs
```

## Architecture

One FastAPI backend (`backend/`) owns all state in SQLite and runs the pipeline in `app/orchestrator.py` as deterministic code: intake → calendar → places → calling → ranking → awaiting_approval → booking → transport → awaiting_contact → completed. Adapters in `integrations/` return typed facts and never write to the database. Three Nemotron calls sit at fixed steps: Nano locally through Ollama (`app/nemotron/local_intake.py`), Lightning through the custom-LLM proxy ElevenLabs calls (`app/routers/llm_proxy.py`), Super for ranking (`app/nemotron/ranker.py`). Every step writes an event; `app/events.py` fans events out to the dashboard over SSE at `GET /api/live`. The Next.js app (`frontend/`) reads `/api/*` only, through a rewrite to the backend, and never changes state except through the REST POSTs for request, approve and contact offer.

Data flows one way. **Never** a frontend import of backend code; **never** an adapter writing state; **never** the orchestrator calling a vendor SDK directly — it goes through `integrations/`.

Full map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development patterns

### Adding or finishing an adapter (`integrations/`)

1. Keep the signature in `docs/ARCHITECTURE.md`, Adapter contracts. If it must change, change the doc in the same PR.
2. Return the Pydantic type from `integrations/types.py`. Raise plain `Exception`s with a message a person can read.
3. Implement the mock mode first (`*_MODE=mock` or `fixture`), reading `backend/fixtures/`. The mock emits the same events as live.
4. Test it in `integrations/tests/`. Live mode is tested by hand once; say so in the PR with the exact command.

### Adding a pipeline step or event (`backend/app/`)

1. Status name goes in `state.py`; transition from and to it is explicit.
2. Event shape goes in `docs/ARCHITECTURE.md`, Live events, and `shared/events.schema.json`, same PR.
3. Side effects are keyed by `task_id + step` and skipped when a receipt exists.
4. Set `visibility` on every event: `owner`, `contact` or `internal`. Default `owner`.
5. Test in `backend/tests/test_pipeline_mock.py` with every adapter mocked.

### Adding an API route (`backend/app/routers/`)

1. One router per concern, one orchestrator or store call per handler. Validate input at the boundary.
2. Viewer scoping on every GET: the contact never receives `owner`-visibility events or `request.text`.
3. Webhooks verify signature or shared secret first, then allowlist, then idempotency key.

### Adding a dashboard component (`frontend/components/`)

1. One component per file. `app/page.tsx` composes and holds no logic.
2. Render from the event types in `frontend/lib/events.ts`. Match `frontend/prototype/index.html` for layout and the `!` chip rule.
3. Owner-only controls (Approve) and contact-only controls (I can drive) check the role from the picker.
4. Large type, high contrast, works at 375 px and 1440 px.

### Turning a rule into a test

When a rule matters, put it in `tests/scenarios/` or `backend/tests/` so it fails on its own. T2 (redaction) and T8 (idempotency) are the two that protect the demo.

## Product rules no test can infer

1. **The raw utterance never leaves the device.** Only the redacted `IntakeRequest` reaches the NVIDIA API, Google, ElevenLabs or any log that ships. Never log the raw text at INFO.
2. **One approval before booking, then no more questions.** No booking and no calendar write before an `approved` event. Completing missing request fields (budget, ride) before calls is intake, not a second gate. The agent decides everything else and reports; it does not propose clinic options to the user.
3. **Status comes from receipts, never from what the agent said.** A `confirmed` Confirmation creates the calendar event, once. Transcript text never changes state or a chip.
4. **The contact gets their scope and nothing else.** Clinic, time, address, the ride need. Nano writes that message from the full record on the device.
5. **Only allowlisted phones, and the agent always says it is an AI.** `DEMO_PHONE_ALLOWLIST` is checked on every outbound call and every inbound SMS. Never a real clinic.
6. **Every adapter has a mock mode that emits the same events**, labelled `simulated: true` where a judge could be misled.
7. **When the docs are silent** and the answer changes what you build: add the question and your default to the Open items in `docs/DECISIONS.md`, say so in the PR, move on. Ask an owner only when two readings mean materially different work.

## Code shape

- **One concern per file.** Past ~300 lines, or doing two jobs, is a split.
- **No dumping grounds.** No `utils.py`, `helpers.ts`. `integrations/types.py` and `frontend/lib/events.ts` are the shared vocabularies.
- **Shared contracts change deliberately** — `shared/*.schema.json`, `docs/ARCHITECTURE.md`, `integrations/types.py`, `.env.example`, this file. Update every consumer in the same PR and say so at the top of the PR body.
- **Model IDs come from `.env`.** Never hard-code or guess a Nemotron model ID.
- **No WebSockets, no global client store.** SSE for live data, REST for actions, `useState` for UI (`docs/DECISIONS.md` D8).

## Process

- **One issue = one PR = one thing**, one to three hours. Branch from `main` only. Merge within the hour it goes green. Never stack on an unmerged PR.
- **Claiming and opening a PR is one command sequence, every time:**
  1. `gh issue edit <n> --add-assignee @me` — the assignee is the claim; two assignees on one issue means stop and ask the coordinator.
  2. `git worktree add ../lifeline-<n> -b <n>-<slug> main`, then `git commit --allow-empty -m "claim: #<n>"`, push, `gh pr create --draft --base main --title "<Area>: <verb> <what> (#<n>)" --body "Closes #<n>"`.
  3. `scripts/check.sh` before every push. Say in the PR body **which commands ran** — never "green locally".
  4. Mark ready for review when the acceptance list is met and the body says what was tested and what is mocked.
  5. Remove the worktree once merged.
- **No issue comments.** The PR body is the record. Comment on an issue only when blocked, in one line naming what you need and from whom.
- **Tests first where a test is possible.** `backend/tests/`, `integrations/tests/`, `tests/scenarios/` mirror the source.
- **No attribution trailers**, in commits or PR bodies.
- **Commit subject:** `<area>: <what is true after this commit>`, ≤72 chars, plain words.
- **PR title:** `<Area>: <Add|Change|Fix|Remove|Tidy> <what is different, in plain words> (#<issue>)`. Areas: `Backend`, `Integrations`, `Frontend`, `Shared`, `Docs`, `Tools`.
- **Pushed history is never rewritten.** A fix is a new commit; a refresh from `main` is a merge, never a rebase.
- **When blocked or unsure, say so.** Do not bypass branch protection, rewrite pushed history or delete data on your own judgment.

## Who reviews and merges

`main` is protected: no direct pushes, **one approving review** from a different GitHub account, stale approvals dismissed on push. `.github/CODEOWNERS` names all three owners, so every PR auto-requests the other two. Any owner may approve and merge with `gh pr merge <n> --merge` — **never squash or rebase-merge**: `git log --format='%an'` is the only way to tell which account wrote a branch. You cannot approve a PR from your own account, so a reviewer session only reviews the other two people's PRs.

**Reviewing is one pass, about three minutes:** read `gh pr diff <n>`, check it against the issue's acceptance list, against `docs/ARCHITECTURE.md` and the product rules above, and against `docs/DECISIONS.md` for anything that quietly reopens a decision. Trust the PR body's named commands for what they prove. Pull and run only when the change is visual or one specific claim smells, and then run that one thing. Request changes with the specific line and the rule it breaks. **If you approve, merge it**; an approved, green, unmerged PR blocks whoever is waiting. No "Reviewing." comments.

## Common issues

- **`EventSource` cannot set headers.** `GET /api/live` is authorised by `viewer_id` and the session cookie, reached through the Next.js rewrite on the same origin.
- **Tunnels and the Next.js dev server buffer SSE.** Send `heartbeat` every 15 s and set `Cache-Control: no-cache, no-transform`, `Content-Encoding: identity`, `X-Accel-Buffering: no`; without `no-transform` the dev server gzips the stream and the browser receives nothing. Test on the real ngrok URL, not localhost, before trusting it.
- **Twilio retries webhooks** on any non-2xx or slow response. Respond 200 fast, do the work after, key everything by `MessageSid`.
- **ElevenLabs calls your proxy with the whole conversation each turn.** `call_id` and the proxy secret arrive in `elevenlabs_extra_body` (sent as `custom_llm_extra_body` when the call starts; dynamic variables do not reach the proxy); never trust the model to repeat it. Details: `docs/ELEVENLABS.md`.
- **Ollama must already be running** or intake fails with a connection error, not a model error. `curl localhost:11434` first.
- **Editing a fixture does not change a running server.** `POST /api/demo/reset` or restart.
- **`pytest` exits 5 when it collects nothing.** An empty test file is not a passing test.
- **Read what a command said, not its last six lines.** A piped `| tail` reports the pipe's exit code, not the command's.
