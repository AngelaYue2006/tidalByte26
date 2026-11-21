# LifeLine — hackathon handoff (context from planning chat)

## Project
LifeLine: a voice agent that phones clinics for the user, finds an appointment that fits their
Google Calendar and budget, books it, and texts the user and their emergency contact.
Primary audience: older adults and their families. Build time: ~8 hours.

Target tracks: NVIDIA "Best Use of Nemotron" (main), ElevenLabs (voice), overall.
Nemotron track judges: core model usage, technical execution, quality of AI output,
impact, differentiation. Must submit a short explanation of what Nemotron does and why.

## Core features (must ship)
1. Request by voice/text -> structured intake (care type, budget, insurance, timing).
2. Private intake on-device: local Nemotron Nano (4-bit, via Ollama/llama.cpp) strips sensitive details.
3. Google Calendar: `freebusy.query` for free windows; `events.insert` to book
   (title "Appointment", visibility private, reminder 1 day before).
   Scopes: `calendar.freebusy`, `calendar.events`.
4. 3 parallel outbound calls to clinics (demo: teammates' phones). Agent opens with
   "Hi, I'm an AI assistant calling for a patient." Asks insurance, price, openings.
5. Decision: hard rules in code first (budget, free time, insurance), then Nemotron 3 Super ranks
   the rest and returns JSON `{clinic, score, reasons[], tradeoff}`. UI shows reason tags
   ("Fits your free time", "Cheapest $95 vs $120", "Closest 1.2 mi") + trade-off sentence.
6. Confirm with user by SMS before booking.
7. Emergency contact SMS: "Appointment booked for Mary: <clinic>, <time>, <address>",
   plus day-before reminder and alert if booking fails.
8. Dashboard (index.html in this folder): request bar, 3 live call cards, explanation card,
   confirmations (user SMS, calendar event, emergency contact SMS).

Cut / stretch: fine-tuning (LoRA on synthetic receptionist calls, before/after eval),
insurance card photo via Gemini, Spanish, real Google Places search (hard-code 3 clinics).

## Nemotron model split
| Job | Model | Why |
|---|---|---|
| Private intake | Nemotron Nano, 4-bit, local | Open weights; health details stay on device |
| Live call agent | Nemotron 3.5 Lightning (NVIDIA API, OpenAI-compatible) | Fast agents; low latency for voice |
| Rank + explain | Nemotron 3 Super | Agent reasoning over price/schedule/distance/insurance |

## Architecture (modeled on github.com/aurelisajuan/TalkTuahBank, HackUTD 2024 winner)
```
Phone <-> Retell AI (STT/TTS, ElevenLabs voice) <-> FastAPI (custom LLM websocket) <- Twilio SMS
FastAPI -> local Nemotron Nano (intake)
FastAPI -> NVIDIA API: Nemotron Lightning (calls), Super (ranking)
FastAPI -> Google Calendar API
FastAPI -> /ws/dashboard -> index.html (same events as replay mode)
```
Key pattern from TalkTuahBank `server/main.py`: Retell connects to `/llm-websocket/{call_id}`;
handle `call_details`, `ping_pong`, `response_required`/`reminder_required`; stream reply chunks
back as `{response_id, content, content_complete, end_call}`. Swap their OpenAI Swarm for
Nemotron calls. Their client has a guided replay mode using the same event contract as live.

Suggested backend files: `main.py` (Retell ws + `/ws/dashboard`), `orchestrator.py`
(intake -> 3 parallel calls -> filter -> rank -> confirm -> book -> notify), `agents.py`
(prompts), `gcal.py`, `notify.py` (Twilio SMS).

## Dashboard event contract (backend must emit exactly these)
```
{ type: "request", text, chips: [..] }            // chip starting with "!" renders green
{ type: "call_start", call_id, clinic, meta }
{ type: "call_status", call_id, status: "dialing"|"live"|"hold"|"done" }
{ type: "transcript", call_id, speaker: "agent"|"clinic", text, audio? }
{ type: "call_result", call_id, price, slot, insured, slotOk }
{ type: "decision", winner, title, reasons: [..], second: [..], tradeoff }
{ type: "booked", calendar, sms_user }
{ type: "notified", sms_contact }
```
index.html: "Play demo" replays `SCENARIO` (timed events, optional `audio/*.mp3` per line);
"Go live" connects to `ws://localhost:8000/ws/dashboard`.

## Demo plan (prerecorded)
1. Once one call works end to end, run the real scenario with teammates as receptionists; save
   call audio (Retell dashboard) or generate clinic voices with ElevenLabs.
2. Cut into clips `audio/a1.mp3`... matching SCENARIO lines; tune `at` timings.
3. On stage: replay mode with audio; story "Mary, 78, needs a dentist; daughter lives 3 hours away."
   Live moment: real Twilio SMS buzzing the "daughter's" phone at the end.
4. Be honest that calls are recorded from the working system; click "Go live" if time allows.
5. Backup: screen-recorded MP4.

## Rules / risks
- Only call team phones; never robocall real clinics. Agent always discloses it's AI.
- Text transcripts only, no audio recording of real people without consent.
- Always confirm with the user before booking.
- First task: verify Retell custom-LLM websocket works with Nemotron replying to a teammate's phone.
