# AGENTS.md — people, roles and the flow of work

> Read `CLAUDE.md` first; it has the rules. This file says who does what. It applies to humans and to every Claude session.

## People and folders

| Person | GitHub | Owns | Avoid without approval |
|---|---|---|---|
| Joyce | `@joyceyouu` | _folder TBD_ | the other two folders |
| Angela | `@AngelaYue2006` (repo admin) | _folder TBD_ | the other two folders |
| Michael | `@mike-rao` | _folder TBD_ | the other two folders |

Folders: `backend/` (orchestrator, Nemotron, state, SSE), `integrations/` (ElevenLabs, Twilio, Google, simulators), `frontend/` (Next.js dashboard, pitch). `shared/`, `docs/`, `tests/scenarios/` and `.env.example` change only by a PR reviewed by the affected owners. The backend owner coordinates integration.

Fill in the folder column once the team picks, then run, per area:
`gh issue list --label area:<folder> --json number --jq '.[].number' | xargs -I{} gh issue edit {} --add-assignee <github>`

## Sessions per person

Each person runs up to three Claude sessions at once, each in its own worktree:

| Role | Count | What it does | What it never does |
|---|---|---|---|
| **Builder** | 1–2 | Takes the open issue assigned to its person with the lowest gate, claims it, builds it, runs `scripts/check.sh`, opens the PR. | Touch another person's folder. Comment on issues. Merge. |
| **Reviewer** | 1 | Reviews PRs from the **other two** accounts in one pass against the issue, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` and the product rules. Approves and merges, or requests changes with the line and the rule. | Approve its own account's PRs. Rewrite code in the PR. |
| **Coordinator** | 1, Joyce's account only | Owns the issue list: splits, re-orders, reassigns, writes new issues when a gap appears, keeps `docs/MVP.md` gates honest, tells builders when a dependency merged. | Build. Review. |

Two builders per person is the ceiling; a third fights the first two for files. At three people that is at most six builders, three reviewers and one coordinator.

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
