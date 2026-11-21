# LifeLine — Pitch

Demo script, Devpost copy, and the Nemotron track explanation. Measured numbers (redaction accuracy, latencies, time-to-booked) are filled by backend issue **#25** (`app/metrics.py` → `metrics.jsonl` → `scripts/metrics_summary.py`) when that lands. Until then the metrics table below stays pending — do not invent a LifeLine wall-clock from the prototype replay.

## What is simulated (say this plainly)

| Piece | Reality in the hackathon demo |
|---|---|
| **Clinic phones** | Teammates' allowlisted phones, or `VOICE_MODE=mock` scripted receptionists. **Never real clinics.** The agent always opens with “Hi, I'm an AI assistant calling for a patient.” |
| **Transport / rides** | Simulated adapter. The demo path returns `UNAVAILABLE_ACCESSIBLE_RIDE` and is labelled **simulated** on the dashboard. Nothing is booked with a real rideshare. |
| **People and insurance** | Synthetic Mary / Sarah, synthetic Delta Dental member ID, fixture addresses. |
| **Places / calendar / SMS** | May be live Google / Twilio or fixture/mock modes; mock modes emit the same events and are labelled when a judge could be misled. |

Booking and calendar writes happen only after one explicit Approve. Status comes from receipts, never from what the agent said on the phone.

---

## 3-minute demo script

From `docs/MVP.md`. Total ≈ 175 s; leave a few seconds of slack.

1. **Story (15 s):** “Mary is 78. Her daughter Sarah lives three hours away.” Show the dashboard with Mary as owner and Sarah as contact.
2. **Request (20 s):** Tap the mic, speak: dental cleaning this week, under $150, Delta Dental, needs a ride. Chips appear with **Processed on device**. Optional: Wi-Fi off for this step, on afterward.
3. **Calls (60 s):** Three cards go Dialing → Live and fill with transcripts. Teammates on their phones are the receptionists (or mock mode). Results: **$95 Thu 9:30 Yes** · **$120 Fri 4:00 Yes** · **$140 Mon 10:00 Yes**.
4. **Decision (20 s):** “Why Nemotron picked Bright Smile Dental” — reason tags plus the trade-off sentence (Smile Co. closer, wrong free window).
5. **Approve (10 s):** Mary’s phone buzzes with the pick; tap **Approve**. Booking confirmed; calendar event appears.
6. **Ride (30 s):** Transport check shows **No accessible ride found (simulated)**. Sarah’s phone buzzes. She replies “I can drive her.” Dashboard shows the ride confirmed.
7. **Close (20 s):** Final texts land; history shows the run. **End on the number:** time to a booked appointment with LifeLine versus calling three clinics yourself — paste the live comparison from #25’s summary once measured. Until then, close on the privacy beat (raw text never leaves the device) and the one-approval story.

**Backup:** `frontend/prototype/index.html` replays the same events with synthesized clinic voices; keep a screen recording of a full live run. The prototype’s scripted `at:` timestamps are demo pacing, not a system measurement.

---

## Nemotron track explanation

### Which model does what

| Model | Where it runs | Job |
|---|---|---|
| **Nemotron Nano (4-bit)** | Laptop via Ollama | Intake redaction → `IntakeRequest` chips; scoped family SMS text. Raw utterance never leaves the device. |
| **Nemotron 3.5 Lightning** | NVIDIA API (ElevenLabs custom LLM proxy) | Live call agent on three concurrent clinic calls. Streams turns; always discloses it is an AI. |
| **Nemotron 3 Super** | NVIDIA API | Ranks surviving offers after hard rules; reason tags + trade-off sentence on the decision card. |

The **code** owns the pipeline order (intake → calendar → places → calling → ranking → approval → booking → transport → contact). Models do not decide the next step.

### Why intake runs locally

From `docs/DECISIONS.md`:

Mary’s raw request can hold symptoms, mobility details, carrier and, in the on-device user record, member ID, DOB, address and Sarah’s number. A clinic only needs care type, budget, carrier name and time windows.

A **cloud** redactor has already received the sensitive text by the time it redacts it. Only a **local** open-weights model gives the property we want: the raw text never leaves the device. Nano turns the utterance into structured JSON, lists `dropped_fields` for metrics, and also drafts Sarah’s scoped message on device. Lightning and Super never see what Nano removed.

Demo beat: Wi-Fi off → speak → chips with **Processed on device** → Wi-Fi on → calls start.

### Measured numbers (pending #25)

Filled by `python scripts/metrics_summary.py` after backend **#25** lands. Paste the script output here and into Devpost. Rows stay pending until then — including time-to-booked for LifeLine. A desk stopwatch of three sequential mock clinic dialogues (no LifeLine) was **201.5 s** on 2026-11-21; that is a manual baseline only. The LifeLine side is **not yet measured** (do not use the prototype’s 15.5 s `booked.at` script constant as a result).

| Metric | Value |
|---|---|
| Redaction kept (fraction of expected fields) | — |
| Redaction dropped (fraction of expected drops) | — |
| Intake latency p50 (ms) | — |
| Intake latency p95 (ms) | — |
| Call-agent first token p50 (ms) | — |
| Ranking latency p50 (ms) | — |
| Bytes sent to cloud per request | — |
| Time to booked — LifeLine (s) | — |
| Time to booked — manual (s) | 201.5 (desk rehearsal; LifeLine not yet measured) |

---

## Devpost

### Tagline

One request, three phone calls, one tap — LifeLine books the appointment and brings family in only when it has to.

### Inspiration

Older adults put off routine care because booking means hold music, repeating insurance details, and looping in a daughter who lives three hours away. We wanted an agent that does the phone work, keeps private details on the device, and asks the family for exactly one thing when a ride is missing.

### What it does

The user speaks a request on a shared dashboard. **Nemotron Nano** redacts it locally. Three AI agents call nearby clinics in parallel (**Nemotron Lightning**). Hard rules drop bad offers; **Nemotron Super** ranks the rest and explains the pick. One Approve books the slot, writes a private calendar event, checks transport, and — if no accessible ride exists (simulated in this demo) — texts the emergency contact, who can reply by SMS or on the contact view.

### How we built it

Deterministic FastAPI orchestrator + SQLite; adapters in `integrations/` (ElevenLabs, Twilio, Google, simulators); Next.js dashboard over SSE. Contracts in `shared/`. Every vendor has a mock mode that emits the same events.

### Challenges

Keeping raw intake off the network; streaming a custom LLM into three concurrent calls; never treating transcript text as booking proof; scoping the contact view so Sarah never sees `request.text`.

### Accomplishments

End-to-end demo path with owner and contact roles, decision reasons, one-approval booking, simulated transport escalation, and a history trail. Local-first privacy story for the Nemotron track.

### What we learned

Smaller local models earn their place when the job is redaction. Ranking and live voice need cloud models — but they should only ever see the redacted request.

### What's next

Live metrics and the time-to-booked comparison from #25’s summary once a real LifeLine run is timed; real Places/Calendar/SMS where still mocked; never real clinic robocalls without consent and legal review.

### Built with

Nemotron Nano (Ollama), Nemotron Lightning, Nemotron Super, ElevenLabs Agents, Twilio, Google Calendar / Places / Distance Matrix, FastAPI, Next.js, SQLite.

### Try it

See `README.md`. Demo phones only on `DEMO_PHONE_ALLOWLIST`. Transport and clinic phones are simulated or teammates — labelled on screen.

### The number we close on

Close on **privacy + one approval** until #25 ships a measured LifeLine time-to-booked. Manual desk baseline only: **201.5 s** for three sequential mock clinic dialogues without LifeLine. Do not claim a LifeLine seconds figure from the prototype replay.
