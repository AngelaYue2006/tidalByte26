# ElevenLabs Agents over Twilio — verified facts (issue #6)

Checked against the vendor documentation on 2026-11-21, then against the live agent (name `LifeLine`, published the same day; its id lives only in `.env`). Field and header names are verbatim. Builders of #20 (proxy), #21 (post-call webhook) and #26 (first live call) build to this file.

## Outbound call

`POST https://api.elevenlabs.io/v1/convai/twilio/outbound-call`, JSON body, authenticated with the `xi-api-key` header (the standard ElevenLabs key header; the endpoint page itself does not restate it).

| Field | Use |
|---|---|
| `agent_id` | `ELEVENLABS_AGENT_ID` |
| `agent_phone_number_id` | `ELEVENLABS_PHONE_NUMBER_ID`, the imported Twilio number |
| `to_number` | the clinic phone, E.164, checked against `DEMO_PHONE_ALLOWLIST` first |
| `conversation_initiation_client_data.custom_llm_extra_body` | `{ "call_id": ..., "proxy_secret": LLM_PROXY_SECRET }`: arrives at the proxy on every turn as `elevenlabs_extra_body` |
| `conversation_initiation_client_data.dynamic_variables` | `{ "call_id": ... }` plus the redacted facts the agent prompt templates; returned in the post-call webhook |
| `call_recording_enabled` | `false` (D14) |

Response: `success`, `message`, `conversation_id` (store as `calls.external_ref`), `callSid` (camelCase).

## Custom LLM (the backend proxy)

- The agent is configured with a server URL and a model id; the server must implement `/v1/chat/completions` (OpenAI Chat Completions). **Verified in the dashboard**: the Server URL field takes the base URL and the agent appends `/chat/completions` itself, so the setting is `PUBLIC_BASE_URL/v1`.
- Replies are Server-Sent Events, `Content-Type: text/event-stream`, each chunk `data: {json}` and a final `data: [DONE]`. Stream from NVIDIA with `stream: true` and relay the chunks.
- **How `call_id` reaches the proxy**: not through dynamic variables. The request body carries `elevenlabs_extra_body`, an object with whatever was passed as `custom_llm_extra_body` at call start. The proxy reads `call_id` and `proxy_secret` from there. **Verified in the dashboard**: the switch is agent Settings → Security → Overrides → "Custom LLM extra body", and it is on for the `LifeLine` agent.
- The docs do not state how a secret for a custom server is sent, so `proxy_secret` travels in `custom_llm_extra_body`, which is documented. The proxy rejects any request whose `elevenlabs_extra_body.proxy_secret` does not equal `LLM_PROXY_SECRET`.
- If the model supports function calling, ElevenLabs system tools (end call) can be used; LifeLine does not need them for the demo.
- Reasoning deltas, if the model emits them, come as `reasoning` or `reasoning_content`; the proxy drops them.

## Post-call webhook

- Configured per workspace (agents settings page) or per agent (agent Settings, "Post-call webhooks"). Use the agent-level setting pointed at `PUBLIC_BASE_URL/api/webhooks/elevenlabs/post-call`.
- Event types: `post_call_transcription`, `call_initiation_failure`. Never subscribe to `post_call_audio` (D14).
- Signature header `ElevenLabs-Signature`, HMAC with the secret generated when the webhook is created: `ELEVENLABS_WEBHOOK_SECRET`. Verify with the SDK's `construct_event(raw_body, signature_header, secret)` before reading the body; it also checks the timestamp.
- Transcription payload: `type`, `event_timestamp`, `data` with `conversation_id`, `status`, `transcript[]` (`role`, `message`, `time_in_call_secs`), `analysis.data_collection_results` (our `price`, `slot`, `insured`), `conversation_initiation_client_data.dynamic_variables` (our `call_id`).
- Failure payload: `data.conversation_id`, `data.failure_reason` (`busy`, `no-answer`, `unknown`) → `CALL_FAILED`.
- Respond `200` fast; retries resend the same payload, so key on `conversation_id`. Ten consecutive failures disable the webhook.

## Agent state (2026-11-21)

- Agent `LifeLine` created and published; first message and system prompt from `integrations/elevenlabs_agent_prompt.md`; Store Call Audio off (D14); data collection fields `price`, `slot`, `insured`, all strings.
- Post-call webhook created at agent level, HMAC-signed, events `post_call_transcription` and `call_initiation_failure` only, pointed at `PUBLIC_BASE_URL/api/webhooks/elevenlabs/post-call` on Joyce's static ngrok domain. `ELEVENLABS_WEBHOOK_SECRET`, `ELEVENLABS_AGENT_ID`, `LLM_PROXY_SECRET` and `PUBLIC_BASE_URL` are set in her local `.env` only.
- The Twilio number import (`ELEVENLABS_PHONE_NUMBER_ID`) is issue #67; see "Importing the Twilio number" below for the steps and where it stands.

## Concurrency and minutes

Read off the team workspace: **Free plan, 4 concurrent calls, 15 included call minutes**, burst beyond the limit at double the per-minute rate. Four concurrent is enough for the three parallel clinic calls. **The 15 minutes are the real cap**: three rehearsals plus the demo (four calls of roughly a minute each, times four runs) exceed it, so either the plan is upgraded before rehearsals or rehearsals run with `VOICE_MODE=mock` and only the demo goes live. Call queueing holds extra calls instead of rejecting them.

## Importing the Twilio number (issue #67)

The agent places calls from a Twilio number that ElevenLabs holds; `ELEVENLABS_PHONE_NUMBER_ID` is the id ElevenLabs gives that imported number. Steps in the ElevenLabs dashboard, as attempted on 2026-11-21:

1. **Channels → Telephony → Import number → From Twilio.**
2. Fill in: a **label** (`LifeLine`), the **phone number** (`TWILIO_PHONE_NUMBER`, E.164), the Twilio **Account SID** and **Auth Token** (the values in `.env`, never written anywhere else).
3. **Routing Region: off** (ElevenLabs picks the region).
4. **Enable inbound SMS: OFF.** The number's inbound texts must keep going to Twilio's own webhook, which is our `PUBLIC_BASE_URL/api/webhooks/twilio/sms`; turning this on would reroute them to ElevenLabs.
5. Import, then on the number's page **assign it to the `LifeLine` agent**. Copy the phone number id into the local `.env` as `ELEVENLABS_PHONE_NUMBER_ID`.

### What happened (2026-11-21)

The import failed at step 5 with ElevenLabs' error that the number was **"not found in your Twilio account as either an incoming number or verified caller ID."** The cause is on the Twilio side, not a typo: the team's Twilio account is a new-style trial. Its Console **Phone Numbers inventory is empty** and says to upgrade to purchase numbers, and the classic API agrees (`IncomingPhoneNumbers` and `OutgoingCallerIds` both return zero; see PR #79). The number Twilio lets a trial send from is a shared trial sender that exists only in the Console's "Try out SMS" dialog. ElevenLabs looks the number up as an `IncomingPhoneNumber` or a verified caller ID of the account, finds neither, and refuses. The same trial also sends only Twilio's predefined SMS templates (PR #79), so this is one limitation with two faces: no owned number, no custom text.

### The two paths (decided 2026-11-21: path one, upgrade and buy)

| Path | What it takes | What it gives |
|---|---|---|
| **Upgrade Twilio and buy a number** | Upgrade the account (card on file), buy one SMS- and voice-capable local number, set it as `TWILIO_PHONE_NUMBER`, repeat the import above, record `ELEVENLABS_PHONE_NUMBER_ID`, re-point Twilio's SMS webhook for the new number at `PUBLIC_BASE_URL/api/webhooks/twilio/sms`. Custom-text SMS from a fresh, unregistered 10DLC number is still carrier-filtered (error 30034) until A2P registration, which takes days, so outbound SMS stays mock either way. | Live outbound calls over ElevenLabs with Nemotron Lightning answering: the #26 first live call and the demo's three parallel calls. |
| **Cut live calls, `VOICE_MODE=mock`** | Nothing to buy. The scripted receptionist simulator (#13) drives the three call cards with the same events, labelled `simulated: true`; the replay prototype carries the synthesized voices for the pitch. #26 and the live half of this issue close as not done. | The demo runs end to end today on mock voice, mock outbound SMS and live inbound SMS; the ElevenLabs track story rests on the agent, the custom-LLM proxy and the post-call webhook, all verified against the live agent without a number. |

### Outcome (2026-11-21, later the same day): path one, taken

- **Twilio upgraded and a number bought.** A local number with voice and SMS ($1.15/month); the compliance profile was approved. A2P 10DLC is **not** registered, so custom outbound text from it would be carrier-filtered: outbound SMS stays `SMS_MODE=mock` for the demo (the owner's decision recorded in PR #79, D16 once #80 lands). Inbound SMS stays live.
- **Import succeeded** with the steps above, Enable inbound SMS **OFF**. The number is assigned to the `LifeLine` agent.
- **Recorded in the root `.env` only:** the new `TWILIO_PHONE_NUMBER` and `ELEVENLABS_PHONE_NUMBER_ID`. They exist; their values appear nowhere else.
- **Webhooks on the number, Twilio Console:** "A message comes in" → `PUBLIC_BASE_URL/api/webhooks/twilio/sms`, HTTP POST (our backend, so a YES or a contact's reply still reaches us); "A call comes in" → ElevenLabs' inbound-call URL, set by the import. Do not point the voice webhook back at the backend; the agent answers calls.
- **Test call, 2026-11-21 about 23:06 UTC:** one outbound call placed from the ElevenLabs dashboard (Telephony → the imported number → Outbound call) to the owner's allowlisted phone. It rang, the `LifeLine` agent spoke, the owner answered; the ElevenLabs conversation history shows duration 7 s, 2 messages, status Successful. **The post-call webhook was not verified in this run:** the backend was not running on :8000 at the time, so the tunnel had nothing to deliver to. The webhook handler itself is covered by #73's tests on main (`backend/tests/test_post_call_webhook.py`); the first live delivery is #26's to record.

The trial finding above stays as history: a new-style Twilio trial cannot be imported into ElevenLabs and cannot send custom text, so a team that wants live calls must upgrade before kickoff ends.

