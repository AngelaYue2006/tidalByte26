# AGENTS.md — people, roles and the flow of work

> Read `CLAUDE.md` first; it has the rules. This file says who does what. It applies to humans and to every Claude session.

## People and folders

| Person | GitHub | Owns | Avoid without approval |
|---|---|---|---|
| Joyce | `@joyceyouu` (Claude Max 20x) | `backend/` — orchestrator, Nemotron, state, SSE, approvals, escalation logic; also `shared/` schemas, fixtures and `tests/scenarios/` | `integrations/`, `frontend/` |
| Angela | `@AngelaYue2006` (repo admin, Claude Pro) | `integrations/` — ElevenLabs, Twilio voice and SMS, Google Calendar, Places, Distance Matrix, receptionist and transport simulators | `backend/`, `frontend/` |
| Michael | `@mike-rao` (Claude Pro) | `frontend/` — Next.js dashboard, owner and contact views, history, demo script and pitch | `backend/`, `integrations/` |

Folders: `backend/` (orchestrator, Nemotron, state, SSE), `integrations/` (ElevenLabs, Twilio, Google, simulators), `frontend/` (Next.js dashboard, pitch). `shared/`, `docs/`, `tests/scenarios/` and `.env.example` change only by a PR reviewed by the affected owners. The backend owner coordinates integration.

Issues are assigned by area label; a reassignment is one `gh issue edit <n> --add-assignee` command and needs no PR.

## Sessions per person

Plans differ, so the ceilings differ. Every session runs in its own worktree.

| Person | Plan | Sessions | Notes |
|---|---|---|---|
| Joyce | Max 20x | 1 coordinator + 2 builders + 1 reviewer | The reviewer reviews **all** of Angela's and Michael's PRs. |
| Angela | Pro | 1 builder + 1 reviewer, not both busy at once | The reviewer wakes only when a Joyce PR is ready; otherwise idle. |
| Michael | Pro | 1 builder + 1 reviewer, not both busy at once | Same. Angela's and Michael's reviewers split Joyce's PRs: Angela takes odd PR numbers, Michael even. |

Pro-plan sessions hit the five-hour usage window fast. Keep them lean: the builder works one issue at a time with mocks first; the reviewer reads the diff and never pulls unless the PR is visual. Use a cheaper model for reviewer sessions. If a Pro account runs out, its reviewer duty passes to the other Pro account for that window and the coordinator says so in chat.

| Role | What it does | What it never does |
|---|---|---|
| **Builder** | Takes the open issue assigned to its person with the lowest gate, claims it, builds it, runs `scripts/check.sh`, opens the PR. | Touch another person's folder. Comment on issues. Merge. |
| **Reviewer** | Reviews PRs from the **other** accounts in one pass against the issue, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` and the product rules. Approves and merges, or requests changes with the line and the rule. | Approve its own account's PRs. Rewrite code in the PR. |
| **Coordinator** | Joyce's account only. Owns the issue list: splits, re-orders, reassigns, writes new issues when a gap appears, keeps `docs/MVP.md` gates honest, tells builders when a dependency merged. | Build. Review. |

## The flow

```
Coordinator writes and assigns issues (labels: area:*, gate:*)
   ↓
Builder claims (assignee) → worktree → claim commit → draft PR → builds → scripts/check.sh → ready
   ↓
Reviewer from another account: one pass → approve + merge, or request changes
   ↓
Builder takes the next issue; coordinator unblocks dependents
```

Gates (`docs/MVP.md`): gate:0 kickoff and contracts, gate:1 vertical slice with mocks, gate:2 real services, gate:3 full integration, gate:4 freeze and pitch. Take gate N+1 only when your gate N issues are merged or the coordinator says so.

## Labels

`area:backend` `area:integrations` `area:frontend` `area:shared` — exactly one per issue.
`gate:0` … `gate:4` — exactly one per issue.
`blocked` — set by the builder with one comment naming the dependency; cleared by the coordinator.

## Token discipline

- No "Reviewing." or "Taking this" comments. Assignee is the claim; the PR is the record.
- One issue comment when blocked, one line. Everything else goes in the PR body.
- Reviewer reads the diff and the PR body; it runs code only for a visual change or one specific doubt.
- Coordinator checks `gh issue list` and `gh pr list` on a cadence, not continuously.

## Safety rules that bind every role

- Only phones in `DEMO_PHONE_ALLOWLIST`. Never a real clinic. The agent always says it is an AI.
- No `.env`, tokens, phone numbers, transcripts of real people or personal data in commits, PR bodies or issue comments.
- Never claim a mock booked anything. Mark simulated pieces as simulated on screen and in the PR.
- Never force-push, bypass protection or delete data on your own judgment.
