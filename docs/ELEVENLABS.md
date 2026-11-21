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
- The Twilio number import (`ELEVENLABS_PHONE_NUMBER_ID`) is its own issue, #67, blocked on the Twilio verification in #7.

## Concurrency and minutes

Read off the team workspace: **Free plan, 4 concurrent calls, 15 included call minutes**, burst beyond the limit at double the per-minute rate. Four concurrent is enough for the three parallel clinic calls. **The 15 minutes are the real cap**: three rehearsals plus the demo (four calls of roughly a minute each, times four runs) exceed it, so either the plan is upgraded before rehearsals or rehearsals run with `VOICE_MODE=mock` and only the demo goes live. Call queueing holds extra calls instead of rejecting them.
