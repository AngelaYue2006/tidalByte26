# LifeLine — Hackathon MVP and Delivery Plan

## Fixed demo scope

**One user goal:** schedule an eye appointment and ensure transport. **One failure:** the preferred simulated transport cannot meet accessibility requirements. **One human escalation:** ask a previously authorized family contact by SMS; the contact offers a ride. **One completion:** confirm appointment + transport + calendar and notify primary user.

**Required connected pieces:** Nemotron planning/tool choice, stateful FastAPI backend, simulated clinic/transport, Google Calendar (test calendar), Twilio SMS and ideally phone, ElevenLabs voice if integration permits, Next.js dashboard with **live call captions** (agent reply streamed as it is generated) and **call/task history**. Use controlled demos and synthetic information.

**Fallbacks:** web text/voice interface for inbound phone; deterministic provider simulator instead of outbound live AI-to-AI call; mock calendar tool instead of live OAuth. Preserve the same API contracts and label mocked components accurately.

## Acceptance criteria (definition of done)

- [ ] Primary user request creates one task with constraints: unavailable Tuesday, morning preference, transport needed.
- [ ] Nemotron chooses relevant tools and changes plan based on actual simulated tool results.
- [ ] Calendar availability is checked; clinic produces a **confirmed** appointment or stays tentative.
- [ ] Transport simulator reports no suitable accessible service.
- [ ] Backend checks `share_transport_assistance` permission before notifying a verified trusted contact.
- [ ] SMS can be received/replied to, and response correlates to the correct task/contact (or demo mock is explicitly labeled).
- [ ] Offer of help is **not** treated as final transport confirmation until required approvals/confirmation obtained.
- [ ] Task and subtask states are persisted; dashboard displays events with timestamps and status.
- [ ] Calendar write occurs only after actual provider confirmation and is idempotent.
- [ ] End result is reported accurately: appointment confirmed, ride confirmed, or outstanding blocker.
- [ ] Team can repeatedly run the same demo without stale state or accidentally texting strangers.
- [ ] During an active call (phone or web-text fallback), the agent's reply appears on the owner's dashboard as it is generated; final caption text = persisted turn text = text sent to TTS.
- [ ] Refreshing the dashboard mid-call restores the conversation with no missing or duplicated text.
- [ ] History lists past calls with a state-derived summary, outcome, transcript and linked event trail; demo reset clears it.
- [ ] Transcripts and the live stream are not accessible to family viewers.
- [ ] At least 6 tested scenarios with results captured for judging.

## Out of scope

Universal outbound calling; real insurance eligibility; real medical data; real transportation booking; financial transactions; medical advice; production-grade auth; unrestricted family visibility; family access to call transcripts; stored audio recordings; production transcript retention policy; multiple Nemotron agents; App Clip; fully custom caregiver permission editor. Show these as roadmap only.

## Demo script (2–3 minutes)

1. **Call:** A teammate plays the grandparent: “I need my eye doctor next week, not Tuesday, preferably in the morning. I also need a ride.” The dashboard's live panel shows the caller's words and captions LifeLine's reply as it speaks.
2. **Plan:** Dashboard shows task and constraints; Nemotron checks calendar and contacts simulated clinic.
3. **Book:** Clinic confirms Thursday 10 AM (example demo fixture); calendar event is created.
4. **Blocker:** Transport tool returns `UNAVAILABLE_ACCESSIBLE_RIDE`.
5. **Escalation:** Backend checks permission; family SMS explains *only* the consented transport need.
6. **Reply:** A teammate texts “I can drive at 9:15.” Or clicks offer in dashboard.
7. **Verify:** LifeLine checks travel timing, requests necessary user approval, confirms ride, updates task.
8. **Close:** Spoken or textual summary, event trail and confirmed statuses; explain what Nemotron decided.
9. **History:** Open the history page. The call just finished appears next to a seeded earlier call, with transcript, outcome and event timeline. Point out that the status chips come from task state, not from what the agent said.

**Demo fixture:** all times, addresses, persons and contacts are synthetic; ensure travel-time check is driven by fixture data, not invented by model.

## Team split

| Owner | Directories | Deliverables | First integration checkpoint |
|---|---|---|---|
| **Person 1 — Agent/backend** | `backend/`, DB and workflow | FastAPI task endpoints, Nemotron tool-call loop, state machine, permissions, events, validation, tests; call/turn persistence, streamed Reply step, SSE live stream, history + demo-reset APIs | `POST /api/tasks` + `GET /api/tasks/{id}` work with mock tools |
| **Person 2 — Voice/integrations** | `integrations/` | Twilio calls/SMS webhooks, ElevenLabs interface, mock clinic, calendar adapter, transport adapter, typed outputs; finalized STT → `conversation.handle_caller_turn`, TTS from reply chunks | Mock `clinic.search_slots` + `clinic.confirm_slot` + SMS adapter ready |
| **Person 3 — Frontend/family** | `frontend/` | Dashboard, task timeline, family view/offer UI, consent display, demo UI; live call panel (EventSource), history list + call detail | Renders seeded task/events from API |

**Shared ownership:** `shared/`, `docs/ARCHITECTURE.md`, and integration tests require PR review from affected owners. Person 1 is integration coordinator; all three own testing/pitch.

## Parallel work order

**Gate 0 — Kickoff (first ~10% of event):** finalize contracts; verify access to model and providers; assign handles; create synthetic users, fixed dates/time zone and fixture contacts. Never wait until integration day to test Twilio credentials.

**Gate 1 — Vertical slice (~10–30%):** text request → Nemotron → mock clinic → task events → dashboard. Person 2 can stub SMS; no real telephony dependency yet. Persist calls and turns from day one through the web-text channel; the dashboard shows completed turns by polling (`LIVE_STREAM_MODE=poll`).

**Gate 2 — Independent features (~30–65%):** exception flow and family escalation; voice calling/SMS, calendar; polished live interface. Token streaming over SSE (Reply step + `/api/owners/{id}/live`), history list/detail pages, demo reset with seeded past calls. Test SSE through the actual tunnel early. Integrate via small PRs continuously.

**Gate 3 — Full integration (~65–80%):** reproducible end-to-end script; backend/API compatibility; permissions; idempotency; dropped call failure cases.

**Gate 4 — Freeze + pitch (~80–100%):** no new risky features; run tests, capture metrics and recorded fallback, rehearse. If event timing differs, use percentages rather than fixed hours.

## Required test matrix

| ID | Scenario | Expected result |
|---|---|---|
| T1 | Standard request | Appointment confirmed, transport requested, family helps, task completes |
| T2 | Clinic only offers Tuesday | Hard day constraint blocks booking; replan or ask user |
| T3 | Calendar conflict | Slot rejected; no event created |
| T4 | Transport unavailable | Task becomes blocked; only authorized contact gets scoped request |
| T5 | Family says no | Task stays unresolved; alternate authorized route or user update |
| T6 | Family reply from unknown phone | No task data leaked; reply rejected/logged safely |
| T7 | Clinic says “we'll confirm later” | Appointment not marked confirmed; calendar not finalized; agent's spoken/captioned reply says tentative, not confirmed |
| T8 | Repeated webhook/retry | No duplicate SMS, booking or calendar event |
| T9 | Appointment rescheduled | Transport revalidated before declaring completion |
| T10 | User revokes family permission | No subsequent sharing/action under revoked scope |
| T11 | Live captions during call | Agent reply deltas arrive in order; final caption = persisted turn = TTS text |
| T12 | Dashboard refresh mid-reply | `snapshot` restores final turns + partial turn; no duplicate or missing text |
| T13 | Family viewer opens live stream or history | 403; no turn text in any family projection |
| T14 | Call drops mid-reply | Partial turn `interrupted`, call `dropped`, task state intact; history shows the dropped call |
| T15 | Two demo runs, then reset | History lists both runs with correct outcomes; reset clears them and reseeds fixtures |

**Metrics to present:** verified task success rate, hard-constraint violations (target 0), false confirmations (target 0, including in spoken/captioned replies), permission violations (target 0), recovery success, response latency, time to first caption token. Report actual counts and conditions, not aspirational rates. Compare against fixed-script baseline if time.

## Prioritization / cut list

1. Never cut Nemotron tool use, real task state, approval checks, or genuine human reply incorporation.
2. If behind: cut outbound clinic voice first; retain simulated structured clinic.
3. Next cut: token-level caption streaming; switch to `LIVE_STREAM_MODE=poll` (completed turns only). Reduce history to the call list + transcript, without the merged event timeline.
4. Next cut: full Google OAuth; use one preauthorized demo calendar or mock.
5. Next cut: family dashboard controls; retain SMS and read-only dashboard.
6. Stretch only after demo works: multi-agent roles, configurable permissions (incl. `view_call_transcript`), barge-in, `Last-Event-ID` replay, rescheduling, broader task types.

## Risks and mitigations

- **Phone setup:** Twilio trial limits and call webhooks may block live demo → web text/voice fallback.
- **Voice latency:** keep calls short; isolate speech layer from orchestration.
- **Calendar:** OAuth/token issues → single demo account and explicit mock mode.
- **Model behavior:** inconsistent tool selections → constrained tool schemas, bounded iterations, explicit test fixtures.
- **Privacy:** consent and phone-number association are mandatory even in prototype → synthetic records and allowlisted contacts.
- **External verification:** a simulated provider is not a real clinic; say so on screen.
- **SSE through tunnels/proxies:** some tunnels and proxies buffer or drop idle streams → heartbeat every 15 s, `Cache-Control: no-cache` and `X-Accel-Buffering: no`, test on the real tunnel in Gate 2, fall back to poll mode.
- **Captions overstating status:** streamed text is generated → Reply prompt gets only the validated projection, status chips come from state, and T7 checks the wording.
- **Nemotron streaming support:** may differ by endpoint or model, or when combined with tool calls → Decide stays non-streamed; if Reply can't stream, send it as one delta.
- **Transcript privacy:** owner-only by default, text only (no audio), cleared on demo reset.

## Last-minute submission checklist

- [ ] All demo data and phone numbers checked; no real customer contacted by accident.
- [ ] All external credentials verified and not committed.
- [ ] Full demo run works twice from a clean task (`POST /api/demo/reset` between runs; history shows only seeded calls + current run).
- [ ] Recorded fallback saved locally; consistent presentation script.
- [ ] Screenshot/log shows actual Nemotron decisions, tool calls and evidence.
- [ ] Pitch explicitly addresses technicality, ingenuity, diversity, applicability, visuals, and Nemotron core usage.
