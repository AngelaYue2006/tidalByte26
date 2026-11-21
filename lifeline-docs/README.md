# LifeLine — Hackathon Starter

**One call for everyday help. Independence for you, peace of mind for your family.**

LifeLine is a **prototype** of a phone-first AI personal advocate. An older adult requests an appointment, an NVIDIA Nemotron orchestrator manages dependencies and decisions, and an authorized family member can help resolve transportation through SMS or a web dashboard.

> **Important:** This repository is a **documentation-first starter**, not a working application. No integration or medical/transportation booking is implemented by these files. The clinic and transport are simulations in the hackathon MVP.

## Read this first

1. [Vision and audience](docs/VISION.md) — why the product exists, differentiation and safeguards.
2. [MVP and execution plan](docs/MVP.md) — one end-to-end demo, acceptance criteria, milestones and test cases.
3. [Architecture and contracts](docs/ARCHITECTURE.md) — service boundaries, schemas, API and event contracts.
4. [Coding-agent collaboration rules](AGENTS.md) — folder ownership, PR rules, handoffs.
5. [Optional agent message board](docs/AGENT_BOARD.md) — GitHub issue workflow inspired by [hackathon-agent-board](https://github.com/azizu06/hackathon-agent-board).

## Scope and decisions

- **Team:** three people. Hackathon duration and agent/editor choices **not provided**; timeline is expressed in percentages, not assumed hours.
- **MVP scenario:** older adult calls → appointment booked with simulated clinic → transport unavailable → authorized family member notified by SMS → family replies → user approves if required → workflow verified and summarized.
- **Architecture:** **one Nemotron orchestrator**, modular tools and deterministic checks. Multiple model agents are a stretch goal.
- **Integrations:** Twilio for calls/SMS, ElevenLabs for speech where practical, Google Calendar for availability/events, Next.js family dashboard, FastAPI backend. Use mock adapters immediately and substitute real ones after vertical slice works.
- **Family UX:** dashboard + SMS with **basic backend permission enforcement**; granular, configurable permissions are stretch.
- **No PHI or real patient information** in demo; use synthetic users and service providers.

## Proposed repo layout

```text
lifeline/
├── README.md
├── AGENTS.md
├── docs/
│   ├── VISION.md
│   ├── MVP.md
│   ├── ARCHITECTURE.md
│   └── AGENT_BOARD.md
├── backend/                 # Person 1: FastAPI, Nemotron, task engine, DB
├── integrations/            # Person 2: Twilio, ElevenLabs, calendar, simulated clinic
├── frontend/                # Person 3: Next.js dashboard, approvals
├── shared/                  # shared schemas/contracts (changes by PR review)
├── tests/                   # cross-system acceptance tests
└── .env.example             # create during implementation; never commit secrets
```

## Kickoff checklist

- [ ] Create clean repo and copy these Markdown files into it.
- [ ] Assign each workstream to an actual GitHub handle in `AGENTS.md`.
- [ ] Confirm hackathon duration, final demo deadline, and judges' Nemotron requirements.
- [ ] Verify Nemotron endpoint and actual model name, Twilio phone/SMS permissions, ElevenLabs interface, Google Calendar OAuth/test calendar, callback hosting and credentials **before** building around them.
- [ ] Agree on the API/schema contract in `docs/ARCHITECTURE.md`.
- [ ] Build a **text → mock tools → task events → dashboard** vertical slice first.
- [ ] Add phone and SMS integrations second; keep deterministic fallback switches.
- [ ] Rehearse the full demo and record one fallback demo with a controlled script.

## How to run (once implemented)

The actual commands depend on generated application files and are intentionally **TBD**. Suggested conventions:

```text
backend: FastAPI on localhost:8000
frontend: Next.js on localhost:3000
integrations: adapters/webhooks handled by backend or separate process
```

Document exact install, environment and startup commands here as each module is merged. Do not assume the current docs alone create runnable services.

## Working rules

- One API/schema source of truth (`docs/ARCHITECTURE.md` until codegen/shared types exist).
- Business integrations return structured facts; only the backend workflow engine may change authoritative task state.
- Never equate a tentative slot or calendar event with a provider-confirmed booking.
- Permission checks and approval gates are implemented in code, not delegated solely to Nemotron.
- See `AGENTS.md` for collaboration and merge protocol.
