# LifeLine — Decision log (merged spec)

> Date: 2026-11-21. This file records the decisions that merged the original LifeLine docs (inbound call, one orchestrator, eye appointment + ride) with the Slotted plan (outbound parallel clinic calls, three Nemotron models, dental cleaning). The current `README.md`, `docs/VISION.md`, `docs/MVP.md` and `docs/ARCHITECTURE.md` already reflect these decisions. The superseded documents are in `docs/archive/` and in git history (commit `f09f0a7` for the LifeLine v0 docs).

| # | Topic | Decision | Why |
|---|---|---|---|
| D1 | Name | **LifeLine** everywhere. Slotted appears only in archived files. | Team decision. |
| D2 | Demo scenario | Mary (78) needs a dental cleaning this week, under $150, with Delta Dental, and needs a ride. Her daughter Sarah is the emergency contact. LifeLine calls 3 clinics, picks one, gets one approval, books it, finds no accessible ride, asks Sarah, Sarah offers to drive, everyone is notified. | Keeps the Slotted booking demo (the differentiator) and adds the LifeLine family step (the impact story). One scenario, one failure, one escalation. |
| D3 | Call direction | **Outbound.** The request is entered on the dashboard (big microphone button or text) by Mary or by Sarah on her behalf. Three AI call agents phone the clinics in parallel. Mary phoning LifeLine is a stretch goal. | The hard, visible part is talking to receptionists. One voice direction to debug in a day. Low effort for the user: speak once, approve once. |
| D4 | Nemotron split | Three models at fixed steps in a deterministic pipeline: **Nemotron Nano (4-bit, local)** for intake redaction and the scoped family message; **Nemotron 3.5 Lightning (NVIDIA API)** as the live call agent; **Nemotron 3 Super (NVIDIA API)** for ranking, the reason tags and the call summaries. No Decide/Reply model loop. Verify exact model IDs on build.nvidia.com at kickoff. | Each model size has a job it is built for. The code, not the model, decides the order of steps, which keeps the demo predictable. See the local-model section below. |
| D5 | User effort | **Exactly one user gate:** approve the pick (tap on dashboard or reply YES by SMS). Everything else runs without asking. Results are reported on the dashboard and by SMS. A per-user "book automatically when it fits my rules" setting is a stretch goal. | Both original doc sets require confirming before booking, and a booking costs money and time. One tap is the floor, not a proposal cycle. |
| D6 | Roles | Two dashboard roles: **owner** (Mary) and **contact** (Sarah). Both see the live dashboard. The contact does not see the raw intake text or anything Nano removed; the contact sees the redacted request chips, the call cards, the decision, the booking and the ride request. The contact can start a request for the owner and can reply by SMS or a dashboard button. | Two-way participation was kept from LifeLine. Nano's redaction is what makes a shared view safe. |
| D7 | Dashboard | **Next.js** app in `frontend/`. The static prototype in `frontend/prototype/index.html` defines how each event renders and is the replay/backup demo. | Team wanted the Next.js app; the prototype is the visual spec. |
| D8 | Browser transport | **Server-Sent Events** at `GET /api/live`, viewer-scoped, with a snapshot on connect and a poll fallback. | Data flows server to browser only; actions are REST POSTs. SSE passes through Next.js rewrites and tunnels, reconnects on its own, and FastAPI serves it with `StreamingResponse`. WebSockets add a second connection type for no gain. |
| D9 | Voice vendor | **ElevenLabs Agents** over **Twilio**, with Nemotron Lightning plugged in as the agent's custom LLM through a thin OpenAI-compatible proxy in the backend (`POST /v1/chat/completions`). Fallback `VOICE_MODE=mock`: a scripted receptionist simulator that emits the same events. | Handles STT, TTS and turn-taking; native Twilio outbound; qualifies for the ElevenLabs track; the NVIDIA API is already OpenAI-compatible, so the proxy only injects per-call context and logs transcripts. Retell was dropped because its custom-LLM path needs a bespoke websocket server. Verify at kickoff: custom LLM with streaming, outbound call API, concurrency of at least 3. |
| D10 | Clinic discovery | **Google Places** Text Search then Place Details for 3 clinics, **Distance Matrix** for miles and drive time from the owner's home. Fallback: a fixture file with 3 clinics and distances. | Kept from Slotted. Distance feeds the ranking and the "Closest 1.2 mi" tag. |
| D11 | State | **SQLite** with `tasks`, `calls`, `turns`, `events`, `contacts`. Task statuses trimmed to `intake`, `calling`, `ranking`, `awaiting_approval`, `booking`, `transport`, `awaiting_contact`, `completed`, `failed`, `cancelled`. Idempotency keys on every webhook and side effect. | Sarah's reply arrives minutes later over a webhook, the history page needs past runs, and the demo must run twice without stale state. A stateless pipeline cannot do any of those. |
| D12 | Transport check | **Simulated** transport adapter driven by a fixture that returns `UNAVAILABLE_ACCESSIBLE_RIDE`. Labelled as simulated on screen. | Real accessible-ride APIs are out of scope; the family escalation is the point of the step. |
| D13 | Repo layout | `backend/` (Person 1), `integrations/` (Person 2), `frontend/` (Person 3), `shared/` and `tests/` by review. | Three people, one folder each, shared contracts by PR. |
| D14 | Audio | Text transcripts only in the live system. The prototype's `audio/*.mp3` clips are ElevenLabs-generated voices for the replay demo, never recordings of real people. | Both original doc sets forbid storing recordings. |

## Why the intake model runs locally (the Nemotron track story)

**What the raw request contains.** When Mary says "I need a cleaning this week, under $150, I have Delta Dental, my knee makes walking hard so I'll need a ride", the text holds symptoms, mobility details, an insurance carrier and, in the user record, her member ID, date of birth, home address and Sarah's phone number.

**What a clinic needs.** Care type, budget cap, insurance carrier name, time windows, and nothing else. That is all a human assistant would say on the phone.

**What Nano does.** Runs on the laptop through Ollama, turns the utterance into `{care_type, budget_max, insurance_carrier, time_windows, needs_ride, search_area}` and drops everything else. Only that JSON goes to the cloud models, to Google Places and into the call prompts. It also writes the scoped message to Sarah from the full record, so the decision about what Sarah may know is made on the device too.

**Why not a cloud model for this step.** A cloud redactor has already received the sensitive text by the time it redacts it. The property we want is that the raw text never leaves the device, and only a local model gives that. Open weights make the redaction auditable. A 4-bit Nano handles a two-sentence request in about a second on a laptop and works with Wi-Fi off, which is also the demo moment: turn Wi-Fi off, speak the request, show the chips appear with the "Processed on device" tag, turn Wi-Fi on, watch the calls start.

**Why the other two models are in the cloud.** The call agent streams replies into three concurrent phone calls; a laptop cannot serve three low-latency streams. Ranking benefits from a larger reasoning model. Neither sees anything Nano removed.

**What we show judges.** Redaction accuracy on a 20-utterance test set (fields kept, fields dropped), intake latency on device, bytes sent to the cloud per request, call-agent response latency, and the reason tags on the decision card.

## Open items to verify at kickoff

- [x] Exact NVIDIA model IDs for Lightning and Super (recorded in `.env.example` on 2026-11-21, #52): `nvidia/nemotron-3.5-lightning-30b-a3b` and `nvidia/nemotron-3-super-120b-a12b`, both on build.nvidia.com behind the OpenAI-compatible endpoint `https://integrate.api.nvidia.com/v1`. The API reference lists `stream` as a request field; confirming it with one real request still needs `NVIDIA_API_KEY` in `.env`.
- ElevenLabs: custom LLM configuration, outbound call API, concurrent call limit on the team's plan.
- Twilio trial: all three teammate numbers verified; SMS webhook reachable through the tunnel.
- Google Cloud project with Calendar, Places and Distance Matrix enabled; OAuth test user added.
- Ollama with a 4-bit Nemotron Nano pulled on the demo laptop. Tag chosen (#52): `nemotron-3-nano:4b-q4_K_M`, the 4-bit GGUF of Nemotron 3 Nano 4B, because the 30B-A3B variant is about 18 GB at 4-bit and too heavy for a laptop demo. Still to do on the laptop: `ollama pull nemotron-3-nano:4b-q4_K_M`, then one completion under 3 s.

## Open items from the shared schemas (#2)

- `call_result.price` and `call_result.slot` are display strings (`"$95"`, `"Thu 9:30"`), as the prototype renders them. The numeric price and ISO slot live in `Offer` and the task `booking`; the dashboard never computes from the event. Default taken in `shared/events.schema.json`.
- `IntakeRequest.time_range` is `{start, end}` as ISO date-times in the owner's timezone, resolved on device from phrases like "this week". Default taken in `shared/intake_request.schema.json`.
