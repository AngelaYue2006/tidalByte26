# Optional GitHub Agent Board — Clean-Repo Setup

## What we're adopting

Inspired by [azizu06/hackathon-agent-board](https://github.com/azizu06/hackathon-agent-board): a **single pinned GitHub issue** acts as a shared message board. Coding agents/humans post progress, tag the relevant teammate, and coordinate cross-module changes. Its README describes `tools/board post`, `unread`, `wait`, `read`, and `whoami`, plus ownership rules in `AGENTS.md`.

**We are adopting the communication convention, not copying its CLI implementation.** No tool script is included in this starter. Starting with a clean repo is fine: use standard `gh` commands and check the board manually. If you want automated polling/wait, separately add the source repo's script after reviewing its license, requirements and security.

## Setup

1. Create a clean LifeLine GitHub repo and copy docs into it.
2. Assign real GitHub handles to roles in `AGENTS.md`.
3. Create one GitHub issue titled `LifeLine Agent Board`; pin it if desired.
4. Record issue number, repository owner/name, and high-level project rules in the first comment.
5. Each developer runs `gh auth login` (only if using GitHub CLI) and checks access.
6. Use comments only for **coordination**, not secrets, transcripts, or private user information.

## Minimal CLI workflow (no extra script needed)

```bash
# Prerequisite: GitHub CLI installed, logged in; run inside the repo

gh issue create --title "LifeLine Agent Board" --body "Shared coordination thread. See AGENTS.md for ownership."
# Note the returned issue number, e.g. 1

gh issue comment 1 --body "[backend] @FRONTEND_HANDLE Task API mock ready. See PR #12."

gh issue view 1 --comments
```

`gh` does not provide the source repo's special `wait/unread` behavior by default. For a hackathon, a quick manual check or brief team standup is generally sufficient.

## Suggested message format

```text
[WORKSTREAM] @RELEVANT_HANDLE
Status: DONE | BLOCKED | NEEDS REVIEW
What changed: branch/PR/files
Contract: endpoint/schema or expectation
Verified: exact test and outcome
Need next: one concrete action
```

Examples:

- `[integrations] @BACKEND_HANDLE DONE: clinic tool now returns {slot_id,status}. Test: 3 simulator cases pass. Wire orchestration to it.`
- `[frontend] @BACKEND_HANDLE BLOCKED: need owner-scoped task events response; propose field visibility in ARCHITECTURE.md.`
- `[backend] @INTEGRATIONS_HANDLE NEEDS REVIEW: transport error code now TRANSPORT_UNAVAILABLE. Check adapter output.`

## Etiquette and guardrails

- Post only **actionable, cross-team** updates; avoid hundreds of low-value progress notes.
- Tag a person when you need a response; otherwise summarize major milestone at merge.
- Do not use board messages as authoritative code review or acceptance evidence; attach tests/PRs.
- Never paste API keys, OAuth tokens, actual phone numbers, medical details, call recordings, or credentials.
- Each owner checks issue comments before picking up dependent work.
- Use small PRs and keep your owned folders isolated; resolve schema changes with human review.

## When not to use it

If teammates are coding directly and communicating actively in person, regular GitHub Issues/PRs plus a quick standup are likely enough. The board is useful only if coding agents operate semi-independently and handoffs are otherwise being lost.

## Reference

Source README reviewed November 21, 2026: https://github.com/azizu06/hackathon-agent-board . Check its current content before copying tooling. This document is our own adaptation of the *workflow idea*, not a verbatim copy of the original implementation.
