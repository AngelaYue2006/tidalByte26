# ElevenLabs Agents over Twilio — verified facts (issue #6)

Checked against the vendor documentation on 2026-11-21. Field and header names are verbatim. Builders of #20 (proxy), #21 (post-call webhook) and #26 (first live call) build to this file; a live call in #26 confirms the two items marked *unverified live*.

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

- The agent is configured with a server URL and a model id; the server must implement `/v1/chat/completions` (OpenAI Chat Completions). Point the server URL at `PUBLIC_BASE_URL/v1`. *Unverified live*: whether the dashboard appends `/chat/completions` or wants the full path; try the base first.
- Replies are Server-Sent Events, `Content-Type: text/event-stream`, each chunk `data: {json}` and a final `data: [DONE]`. Stream from NVIDIA with `stream: true` and relay the chunks.
- **How `call_id` reaches the proxy**: not through dynamic variables. The request body carries `elevenlabs_extra_body`, an object with whatever was passed as `custom_llm_extra_body` at call start. The proxy reads `call_id` and `proxy_secret` from there. *Unverified live*: some agent dashboards have a "Custom LLM extra body" switch under the agent's security settings; if the key is missing from the first request, enable it.
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

## Concurrency

The limit is per subscription and is shown on the pricing page and in the workspace, not in the docs. **Still to read off the team account.** If the plan allows fewer than three concurrent conversations: burst pricing lets an agent run up to three times its limit at double the per-minute rate, and call queueing holds extra calls instead of rejecting them. `VOICE_MODE=mock` is the fallback either way.
