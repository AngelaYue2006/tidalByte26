# LifeLine — Hackathon MVP and Delivery Plan

## Fixed demo scope

**One request:** Mary needs a dental cleaning this week, under $150, with Delta Dental, and needs a ride. **One comparison:** three clinics called in parallel; Bright Smile Dental wins on fit, price and insurance. **One approval:** Mary taps Approve. **One failure:** the simulated transport check finds no accessible ride. **One escalation:** Sarah, the emergency contact, is texted a scoped request and replies that she can drive. **One completion:** appointment confirmed, calendar event created, ride confirmed, both notified, dashboard shows the whole trail.

**First-time dental demo:** Send “I need a dental cleaning.” Answer the spending-limit and ride questions one at a time, then start the three simulated calls. Repeat with “I need a dental cleaning under $150 and I need a ride” to skip both questions. Reload between questions to check resume. Switch to Sarah to check that only Mary can answer. Enter a cap below $95 to exercise the no-offer outcome.


**Required connected pieces:** local Nemotron Nano intake (Ollama), Google Calendar free/busy and insert, Google Places and Distance Matrix, three outbound ElevenLabs calls over Twilio with Nemotron Lightning answering, Nemotron Super ranking with reason tags, SQLite task state, SSE live stream, Next.js dashboard with owner and contact views, Twilio SMS both ways, simulated transport adapter.

**Fallbacks (same events, labelled on screen):** `VOICE_MODE=mock` scripted receptionists; `PLACES_MODE=fixture` three hard-coded clinics; `CALENDAR_MODE=mock`; `SMS_MODE=mock` writes to the dashboard instead of sending; `LIVE_STREAM_MODE=poll`.

## Acceptance criteria

- [ ] A spoken or typed request produces the redacted request chips within 3 s on device, with the raw text never sent to any network endpoint (verified by the backend log of outbound requests).
- [ ] Google Calendar free windows are fetched before any call starts.
- [ ] Three clinics are found with phone numbers and drive distance, or loaded from the fixture with the fallback label shown.
- [ ] Three calls start within 2 s of each other; each call card shows live transcript lines and ends with price, slot and insurance.
- [ ] The agent opens every call with "Hi, I'm an AI assistant calling for a patient."
- [ ] Hard rules remove offers over budget, outside free windows or not covered; Super ranks the remainder and returns JSON with a score, at least two reasons and a trade-off sentence.
- [ ] Nothing is booked until the owner taps Approve or replies YES; the task is `awaiting_approval` until then.
- [ ] The booking call-back (or mock) returns a confirmation before the calendar event is created; the event is created exactly once with title "Appointment", private visibility and a one-day reminder.
- [ ] The transport adapter returns `UNAVAILABLE_ACCESSIBLE_RIDE`; the task moves to `awaiting_contact`; the contact SMS contains only clinic, time, address and the ride need.
- [ ] Sarah's reply from the allowlisted number (or her dashboard button) is matched to the task; a reply from an unknown number is rejected and logged.
- [ ] Final SMS to both phones; dashboard shows `completed` with the event trail.
- [ ] The contact view never shows the raw request text or anything Nano dropped.
- [ ] Refreshing the dashboard mid-run restores the current state from the SSE snapshot.
- [ ] `POST /api/demo/reset` clears the run and reseeds fixtures; the full demo runs twice in a row.
- [ ] Nemotron metrics captured: redaction accuracy on the 20-utterance set, intake latency, call-agent response latency, ranking latency.

## Out of scope

Real clinic calls; real transport booking; insurance eligibility checks; medical advice; production auth; audio recording; phone-in intake; fine-tuning; Spanish; multiple appointment types; configurable permission editor. Show these as roadmap only.

## Demo script (3 minutes)

1. **Story (15 s):** "Mary is 78. Her daughter Sarah lives three hours away." Show the dashboard with Mary's name and Sarah as contact.
2. **Request (20 s):** Tap the mic, speak the request. Chips appear with "Processed on device". Optional: Wi-Fi off during this step, on afterward.
3. **Calls (60 s):** Three cards go Dialing, Live, and fill with transcripts. Teammates on their phones are the receptionists. Results fill in: $95 Thu 9:30 Yes; $120 Fri 4:00 Yes; $140 Mon 10:00 Yes.
4. **Decision (20 s):** "Why Nemotron picked Bright Smile Dental" with reason tags and the trade-off sentence.
5. **Approve (10 s):** Mary's phone buzzes with the pick; tap Approve on the dashboard. Booking confirmed; calendar event appears.
6. **Ride (30 s):** Transport check shows "No accessible ride found (simulated)". Sarah's phone buzzes on stage. She replies "I can drive her." Dashboard shows the ride confirmed.
7. **Close (20 s):** Final texts land; history page shows the run. End on the number: time to a booked appointment with LifeLine versus calling three clinics yourself.

**Backup:** `frontend/prototype/index.html` replays the same events with synthesized clinic voices; a screen recording of a full live run.

## Team split (3 people)

| Owner | Directory | Deliverables | First checkpoint |
|---|---|---|---|
| **Person 1 — Backend and AI** | `backend/` | FastAPI app, orchestrator pipeline, Nano intake via Ollama, Lightning custom-LLM proxy, Super ranker, hard rules, SQLite state, event bus and SSE, approvals, demo reset, Nemotron metrics | `POST /api/requests` with all adapters in mock mode drives the full event sequence to `GET /api/live` |
| **Person 2 — Voice and integrations** | `integrations/` | ElevenLabs agent setup and outbound call API, Twilio SMS send and webhook, Google Calendar, Places, Distance Matrix adapters, transport and receptionist simulators, typed outputs | One real call to a teammate's phone with Nemotron answering, transcript posted back to the backend |
| **Person 3 — Frontend and pitch** | `frontend/` | Next.js dashboard: request bar with mic, three call cards, decision card, approval button, transport and contact cards, confirmations, owner and contact views, history page, SSE client; demo script and Devpost write-up | Dashboard renders the full event sequence from the mock backend |

`shared/` schemas and `docs/ARCHITECTURE.md` change only by PR reviewed by the affected owners. Person 1 coordinates integration. All three own the pitch.

## Parallel work order (percent of build time)

**Gate 0 — Kickoff (0–10 %):** verify every external service from the kickoff checklist in `README.md`. Agree `shared/` contracts. Pull Nano into Ollama. Create synthetic fixtures: Mary, Sarah, three clinics with phone numbers and distances, Mary's free windows.

**Gate 1 — Vertical slice (10–30 %):** text request → Nano → fixture clinics → mock receptionists → hard rules + Super → approval → mock booking → mock transport → mock SMS → events over SSE → dashboard. Everything mocked except the two Nemotron cloud calls and Nano.

**Gate 2 — Real services (30–65 %):** Person 2 lands one real ElevenLabs call, then three concurrent. Real Calendar, Places and Distance Matrix. Real Twilio SMS both ways through the tunnel. Person 3 adds the contact view, history and polish. Person 1 adds persistence, idempotency and metrics.

**Gate 3 — Full integration (65–80 %):** full run with teammates as receptionists, three times. Fix timing. Capture metrics. Record the backup video.

**Gate 4 — Freeze and pitch (80–100 %):** no new features. Rehearse. Write the Nemotron explanation and the Devpost.

## Test matrix

| ID | Scenario | Expected result |
|---|---|---|
| T1 | Standard run | Bright Smile picked, approved, booked, ride via Sarah, `completed` |
| T2 | Raw request with symptoms and member ID | Chips contain neither; outbound request log shows no raw text |
| T3 | All three offers over budget | No pick; task `failed` with reason; owner and contact told honestly |
| T4 | Offer outside free windows | Removed by hard rules before ranking; shown in red on the card |
| T5 | Clinic does not take the insurance | Removed by hard rules; card shows Insurance: No |
| T6 | Owner does not approve within the timeout | Task stays `awaiting_approval`; reminder SMS once; no booking |
| T7 | Clinic says "we'll call back to confirm" | Appointment `tentative`; no calendar event; dashboard says so |
| T8 | Repeated Twilio webhook | No duplicate SMS, booking or calendar event |
| T9 | Reply from a number not on the allowlist | Rejected, logged, no task data leaked |
| T10 | Contact declines | Task `awaiting_contact` stays open; owner told; no false ride confirmation |
| T11 | Dashboard refresh mid-call | Snapshot restores cards and transcripts; no duplicates |
| T12 | Two runs then reset | History shows both; reset clears and reseeds |

**Metrics to present:** redaction accuracy (fields kept and dropped on 20 utterances), intake latency on device, call-agent first-token latency, ranking latency, hard-rule violations (target 0), false confirmations (target 0), time to booked appointment versus manual baseline.

## Cut list, in order

1. Never cut: Nano intake, three calls (mock allowed), hard rules + Super ranking, one approval, contact SMS, SSE dashboard.
2. Cut Distance Matrix; use straight-line distance from Places coordinates.
3. Cut real Places; use the fixture.
4. Cut Google OAuth; use one pre-authorized demo calendar or mock.
5. Cut live ElevenLabs calls; use the receptionist simulator and the replay prototype with synthesized voices.
6. Cut history page; keep live view only.

## Risks and mitigations

- **Three concurrent calls:** plan limits or trial restrictions → verify at kickoff; stagger by 2 s if needed; mock mode is one flag away.
- **Custom LLM latency:** receptionists hang up on slow agents → Lightning, short system prompt, stream, measure first-token latency.
- **Nano accuracy:** misses a field → constrained JSON schema in the prompt, 20-utterance test set, deterministic regex backstop for dollar amounts and carrier names.
- **Webhooks through tunnels:** → one ngrok URL in `.env`, test SMS round trip in Gate 0.
- **Agent overstates on the phone:** → status comes only from structured call results and the booking confirmation; T7 checks wording.
- **Privacy:** → synthetic data, allowlisted phones, contact view projection tested in T2.

## Submission checklist

- [ ] No real clinic called; all numbers checked.
- [ ] No credentials in the repo.
- [ ] Full demo run works twice from reset.
- [ ] Backup video saved locally and uploaded.
- [ ] Nemotron explanation written: which model does what, why local for intake, measured numbers.
- [ ] Devpost covers technicality, ingenuity, diversity, applicability, visuals and Nemotron core usage.
