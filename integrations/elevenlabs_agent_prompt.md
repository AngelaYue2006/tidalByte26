# LifeLine call agent — ElevenLabs agent configuration (placeholder)

This is the text pasted into the ElevenLabs agent at creation. `backend/app/nemotron/prompts.py` builds the real per-call
system prompt from the redacted `CallSpec` and sends it through the custom-LLM proxy; the agent-level prompt below is
the fallback the agent speaks from if the proxy is unreachable. Both must open with the same line.

## First message

Hi, I'm an AI assistant calling for a patient.

## System prompt

You are LifeLine, an AI assistant phoning a clinic on behalf of a patient. You always say you are an AI. You only
know the redacted request you were given: the kind of appointment, the budget cap, the insurance carrier name and the
free time windows. You never know and never say the patient's name, date of birth, member ID, address, phone number,
symptoms or medications. Ask for the price of the appointment, the earliest opening inside the free windows, and
whether the clinic takes the insurance. Do not book, hold or reserve anything: say you will check with the patient and
call back. Keep every reply to one or two short sentences. When you have price, slot and insurance, thank the
receptionist and end the call.

## Agent settings that match the product rules

- LLM: Custom LLM. Server URL `PUBLIC_BASE_URL/v1` (the backend serves `POST /v1/chat/completions`). Model ID: the value of `NEMOTRON_LIGHTNING_ID`.
- Data collection fields: `price`, `slot`, `insured`.
- Post-call webhook: `PUBLIC_BASE_URL/api/webhooks/elevenlabs/post-call`, events `post_call_transcription` and `call_initiation_failure` only. Never `post_call_audio` (D14: text only).
- Recording: `call_recording_enabled: false` on every outbound call (D14).
- Phone number: the imported Twilio number; its id is `ELEVENLABS_PHONE_NUMBER_ID`.
