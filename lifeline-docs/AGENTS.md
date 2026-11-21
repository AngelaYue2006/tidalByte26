# LifeLine — Coding-Agent and Team Rules

> Read `README.md`, `docs/MVP.md`, and `docs/ARCHITECTURE.md` before generating code. This file applies to human collaborators and AI coding agents. It is a coordination policy, not autonomous permission to access accounts or contact people.

## Mission and non-goals

Ship **one safe, complete, reproducible MVP**: phone/text request → Nemotron planning → simulated clinic appointment → simulated inaccessible transport → approved family SMS response → verified completion and dashboard (with live call captions and call history). Do not expand scope into real clinical advice, real patient data, unrestricted live booking, or full multi-agent architecture.

## Ownership (replace placeholders with GitHub handles)

| Role | GitHub handle | Owns | Avoid without approval |
|---|---|---|---|
| Person 1 — backend/AI | `@BACKEND_HANDLE` | `backend/`, backend tests, state machine, DB, Nemotron | `integrations/`, `frontend/` |
| Person 2 — voice/services | `@INTEGRATIONS_HANDLE` | `integrations/`, service adapter tests | `backend/`, `frontend/` |
| Person 3 — frontend/family | `@FRONTEND_HANDLE` | `frontend/`, frontend tests | `backend/`, `integrations/` |
| Shared | review required | `shared/`, `docs/ARCHITECTURE.md`, `tests/` integration tests | breaking interfaces without review |

**Backend owner is integration coordinator**, not unilateral decision-maker. Make small PRs, notify affected owners, and merge working vertical slices frequently.

## Source of truth

- **Why**: `docs/VISION.md`.
- **What we actually ship**: `docs/MVP.md`.
- **How components talk**: `docs/ARCHITECTURE.md`.
- **How to run**: `README.md` (update with real commands once app exists).
- API contracts must match shared types/tests. Escalate disagreements before implementing contradictory assumptions.

## Coding-agent work contract

Every assignment must identify: owner, allowed files, dependencies, request/response interfaces, acceptance test, mock/live mode, and who to ping on completion.

Before coding: read docs, inspect existing code and tests, run quick compatibility check, and announce blockers. While coding: work within owned paths, prefer small cohesive changes, never invent real API results, add tests and documentation. When complete: report changed files, how tested, remaining known issues, and exact integration handoff.

### Agent-safe and human-safe rules

- Do not read, print, commit, screenshot or post `.env` secrets, tokens, full call recordings, or private user details.
- Never call real numbers or send SMS except **allowlisted, consented test contacts**.
- Never claim a simulated clinic confirmed a real appointment.
- Do not modify a different owner's files without permission; coordinate shared-schema changes.
- Do not use model-generated free text as proof of permission or external confirmation.
- Do not mark task completed without validated provider evidence and all required subtasks.
- Avoid large refactors during final freeze; prioritize runnability.
- Never auto-merge PRs that change security-sensitive or external side-effect code without a human review.

## Pull request checklist

- [ ] Scoped to owned area, or explicit cross-owner approval attached.
- [ ] Shared contracts unchanged, or updated in `docs/ARCHITECTURE.md` and affected tests.
- [ ] Tests run and actual results documented.
- [ ] No tokens, phone numbers, personal data or generated secrets committed.
- [ ] Mock mode remains available; external side effects idempotent.
- [ ] Integration owner notified with endpoint/schema details.

## Coordination without extra tooling

Use one pinned GitHub issue named **LifeLine Agent Board** (optional, see `docs/AGENT_BOARD.md`). Post high-signal messages when APIs are ready, dependencies are blocked, or shared schemas change. Prefix messages with `[backend]`, `[integrations]`, `[frontend]` and tag the affected handle. Agents should read new posts at the start of each assignment and after completing it; a human remains responsible for priorities and merges.

Example:

```text
[backend] @FRONTEND_HANDLE GET /api/tasks/{id} ready on branch feat/task-api.
Fields match docs/ARCHITECTURE.md. Test: pytest tests/test_task_api.py (pass).
Please wire dashboard; waiting on family SMS callback adapter.
```

If you later copy the original `tools/board` script from hackathon-agent-board, follow its license and current instructions; **these docs alone do not provide that script**.

## Demo integration protocol

Before declaring a component done, run one scenario that includes it and verify events and status in the dashboard. Keep a known-good branch and record a fallback demo. In the last ~20% of time, stop risky features and focus on test failures, latency, and story.
