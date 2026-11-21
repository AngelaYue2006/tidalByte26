# LifeLine

**One request, three phone calls, one tap. LifeLine books the appointment and brings the family in only when it has to.**

LifeLine is a hackathon prototype of a voice agent for older adults and the people who help them. The user says what they need. A local Nemotron model strips out anything a clinic doesn't need to hear. Three AI call agents phone nearby clinics at the same time, ask about insurance, price and openings, and a larger Nemotron model ranks the answers and explains the pick. The user approves with one tap, LifeLine books it, adds it to Google Calendar, checks for a ride and, if there is no accessible option, texts the emergency contact, who can reply by text or on the shared dashboard.

> **Status:** documentation and skeleton only. Nothing in this repository books real appointments yet. Clinics in the demo are teammates' phones; transport is simulated.

## The demo in one paragraph

Mary, 78, taps the microphone on the dashboard: "I need a dental cleaning this week, under $150. I have Delta Dental. I'll need a ride." Her daughter Sarah lives three hours away and is her emergency contact. Nano, running on the laptop, turns the request into chips: Dental cleaning · Max $150 · Delta Dental · Free Tue pm, Thu am · Needs ride · Processed on device. Three call cards appear and fill with live transcripts. Bright Smile Dental has Thursday 9:30 for $95. The decision card says why: fits her free time, cheapest, takes Delta, 1.2 miles. Mary taps Approve. The calendar event appears. The transport check comes back with no accessible ride, so Sarah's phone buzzes: "Mary has a dentist appointment Thu 9:30 at 123 Main St and needs a ride. Can you help?" Sarah replies "I can drive her." The dashboard shows the ride confirmed and both phones get the final text.

## Read this first

1. [docs/DECISIONS.md](docs/DECISIONS.md) — every design decision and why, including the local-model justification for the Nemotron track.
2. [docs/VISION.md](docs/VISION.md) — who it is for and what makes it different.
3. [docs/MVP.md](docs/MVP.md) — exact demo scope, acceptance criteria, team split, gates, test matrix.
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — pipeline, data model, REST and SSE contracts, adapter signatures, environment variables.
5. [AGENTS.md](AGENTS.md) — rules for humans and coding agents working in this repo.
6. [docs/PITCH.md](docs/PITCH.md) — 3-minute demo script, Devpost copy, Nemotron explanation; refresh metrics with `python scripts/metrics_summary.py`.
7. [docs/AGENT_BOARD.md](docs/AGENT_BOARD.md) — optional GitHub-issue message board.

Archived: `docs/archive/` holds the original Slotted plan and handoff. The LifeLine v0 docs (inbound-call design) are in git history at commit `f09f0a7`.

## Repo layout

```text
.
├── README.md, AGENTS.md, CLAUDE.md
├── docs/                     # vision, MVP, architecture, decisions, agent board, archive/
├── backend/                  # Person 1: FastAPI, orchestrator, Nemotron, state, SSE
│   └── app/
│       ├── main.py           # app factory, routers, SSE
│       ├── orchestrator.py   # intake → places → calls → rank → approve → book → transport → notify
│       ├── ranking.py        # hard rules, then Super
│       ├── state.py          # task status transitions
│       ├── events.py         # event bus + SSE fan-out
│       ├── db.py, models.py  # SQLite tables
│       ├── nemotron/         # local_intake.py (Nano), call_agent.py (Lightning proxy), ranker.py (Super), prompts.py
│       └── routers/          # requests.py, tasks.py, live.py, approvals.py, contacts.py, webhooks.py, llm_proxy.py, demo.py
├── integrations/             # Person 2: ElevenLabs, Twilio, Google, simulators
├── frontend/                 # Person 3: Next.js dashboard; prototype/ holds the static replay demo
├── shared/                   # event and schema contracts (JSON Schema); change by PR review
├── tests/                    # cross-system scenario tests (T1–T12 in docs/MVP.md)
└── .env.example              # every variable, no values
```

## Running it (once implemented)

```text
backend:   uvicorn app.main:app --reload --port 8000     (from backend/)
frontend:  npm run dev                                   (from frontend/, port 3000)
ollama:    ollama run <nemotron-nano-4bit-tag>           (local intake model)
tunnel:    ngrok http 8000                               (Twilio + ElevenLabs webhooks)
```

Fill in exact commands as each module lands. Secrets live in `.env`, never in the repo.

## Kickoff checklist

- [ ] Verify NVIDIA model IDs, streaming support, and the API key.
- [ ] Verify ElevenLabs custom-LLM setup, outbound call API and concurrent-call limit.
- [ ] Verify all three teammate phones on the Twilio trial; SMS webhook reaches the tunnel.
- [ ] Google Cloud project: Calendar, Places, Distance Matrix enabled; OAuth test user added.
- [ ] Ollama running a 4-bit Nemotron Nano on the demo laptop.
- [ ] Agree `shared/` contracts; then build the text → mock calls → events → dashboard slice first.
- [ ] First risky task: one real outbound call to a teammate with Nemotron answering, returning price and slot as JSON.

## Rules

- Call only team phones. Never robocall real clinics. The agent always says it is an AI.
- Text transcripts only. No audio recordings of real people. Replay clips are synthesized voices.
- One approval before booking, always.
- Synthetic users, synthetic insurance, synthetic addresses. No real patient data.
