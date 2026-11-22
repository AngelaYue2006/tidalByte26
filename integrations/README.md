# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
Calendar, Places, distance and SMS support live modes as described below.
Voice implementations are separate work (#13 and #26).

The defaults are `CALENDAR_MODE=mock`, `PLACES_MODE=fixture`, `SMS_MODE=mock`,
and `TRANSPORT_MODE=fixture`. The backend loads its environment; these adapters
read process environment variables and never load or print `.env` themselves.

Calendar, clinic discovery, distances and synthetic inbound identity mapping read
`backend/fixtures/`. Calendar windows are clipped to the requested range. Fixture
discovery supports the fixture care type and area (or `near home`); unsupported
searches return no clinics. Fixture drive times support only the synthetic home,
match clinics by place ID, and preserve input order. These limitations prevent
inventing fixture answers for unrelated requests.

There is no transport fixture in `backend/fixtures/`, so the owned synthetic
`integrations/fixtures/transport.json` supplies the unavailable ride result.
Transport outputs are always simulated. No ride is booked.

## Orchestrator consumption

- `sms.send(...)` returns a `MessageReceipt`. Publish
  `receipt.dashboard_event("owner" | "contact")` using the existing backend
  event bus with the appropriate task and viewer visibility. The payload carries
  `simulated: true`, the message copy, and no phone number. Adapters do not import
  the backend event bus or write database rows. This PR supplies the payload;
  actual dashboard delivery requires the orchestrator to publish it.
- `transport.check(...)` returns `TransportOptions`; its `dashboard_event()` is
  the schema-valid simulated `transport_check` payload.
- Fake calendar and SMS receipt IDs are deterministic for owner/recipient plus
  idempotency key. They are not a persistent idempotency store. The backend still
  checks approval and saved receipts before invoking side effects. Calendar
  refuses tentative/rejected bookings, and returns private `Appointment` metadata
  with a 1440-minute reminder for confirmed bookings.
- Windows retain exactly `start` and `end`, compatible with the shared schema.
  Clinic/distance facts and simulated receipts carry `simulated: true`; mark the
  resulting discovery/calendar events as simulated when composing them.

## Synthetic inbound SMS

`parse_inbound(form)` in mock mode accepts synthetic forms. `From` must pass
`DEMO_PHONE_ALLOWLIST` and match a synthetic owner/contact in `users.json`.
`MessageSid` and `Body` are required; optional `task_id` is returned as correlation
metadata, never proof that a task is waiting. The backend must match the sender
and waiting task before applying an approval or contact response. Fixture phones
must be explicitly allowlisted for mock SMS too; there is no safety bypass.

Mock inbound messages are marked simulated and are not authenticated Twilio
webhooks. Live mode requires the authenticated request envelope described below.
Do not expose mock parsing as a trusted public webhook.

## Validation

`python -m pytest -q integrations/tests/test_adapters_mock.py` exercises fixtures,
window clipping, confirmed-only calendar receipts, repeat receipt identities,
allowlist failures, inbound role mapping and shared-schema dashboard payloads.
Sockets are forbidden throughout that suite. `scripts/check.sh` runs all repository
checks; use an environment with Ruff, pytest and backend dependencies installed.

## Live Google Calendar (#28)

`CALENDAR_MODE=live` uses the OAuth demo account's primary calendar. The only
supported owner is the fixture owner ID; unknown owner IDs fail before contacting
Google. The backend loads `.env` into the process environment; the adapter never
loads a file or logs credentials. Required settings already exist:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `APP_TIMEZONE`.
OAuth uses only `calendar.freebusy` and `calendar.events`. No model IDs are needed
to call these adapters in isolation.

`free_windows(owner_id, start_iso, end_iso)` validates timezone-aware bounds,
queries `freebusy.query`, clips and merges all busy intervals, and returns their
complement in `APP_TIMEZONE`. Merging is in UTC so daylight-saving folds are
handled correctly. A missing calendar, per-calendar error or malformed interval
fails closed instead of pretending the whole range is available.

`create_event(owner_id, booking, idempotency_key)` requires a confirmed Booking.
It inserts a private event titled `Appointment`, with clinic/address description,
location, configured timezone and a popup reminder 1440 minutes before the event.
No attendees are added and `sendUpdates=none` suppresses invitations. The caller
still must enforce the approved task state; a typed confirmed Booking by itself
is not an authorization gate. The adapter does not read or write database state.

The event ID is a Google-compatible hash of owner ID plus idempotency key (the
backend supplies task ID plus step). A repeated insert gets HTTP 409, fetches the
existing event and verifies the content hash and actual title, status, location,
description, times, visibility and reminders before returning the receipt. A
reused key for different contents or an edited/cancelled event fails, rather than
confirming the wrong event. Timeouts do not return a receipt; a later retry with
the same key can recover a previously committed insert. Tokens, URLs and vendor
response bodies are not included in adapter error messages.

`Booking.address: str | None = None` now carries the selected clinic address.
The orchestrator (#11, backend owner) must copy `Clinic.address` into this field
when building a confirmed Booking. The adapter uses a supplied address verbatim,
even when the clinic name collides with a fixture name. An explicitly blank
address fails before insertion. Only an absent address (`None`, the backwards
compatible default) falls back to the known fixture clinic by name; unknown
clinics without an address fail closed. The fixture fallback supports existing
mock callers, not arbitrary live bookings. Public function signatures and
`shared/task.schema.json` (the API projection) are unchanged. No backend files
are edited here; backend population of this optional field is a named dependency.

The live hand test uses only `free_windows`; no real calendar event was inserted.
Event creation, duplicate recovery, mismatched receipts and network errors are
covered against an in-memory vendor and `httpx.MockTransport`. This proves the
adapter behavior without claiming a real booking or bypassing task approval.

## Live discovery and driving distances (#29)

Set `PLACES_MODE=live` and `GOOGLE_MAPS_API_KEY` in the backend environment.
Enable Places API (New) and Routes API for that key. Text Search sends only
`<care_type> near <area>` with a `places.id` field mask; Place Details requests
only name, address, coordinates and international phone. The live limit is 0-3;
missing required detail fields fail safely rather than return incomplete facts.
No vendor response bodies or phone values are logged by these adapters.

Configure `DEMO_PHONE_ALLOWLIST` in order with the teammate phones for the clinic
roles. Live search requires at least one distinct E.164 allowlisted phone per
requested result **before** making any Google request. The first three numbers
map to the first three search results. Source clinic phones are validated and
discarded; they never escape this boundary. Returned clinics have `simulated=True`
because the phone substitution makes the demo synthetic, even though the name,
address and coordinates come from Google. A count-only INFO log explicitly
records the substitution. The call adapter must still recheck the allowlist on
every dial and disclose that it is AI in its first line. Discovery never dials.

`drive(origin, clinics)` accepts an address, a `{lat, lng}` dict, or a two-item
latitude/longitude sequence. It preserves clinic order and calls Routes
`computeRoutes` with `DRIVE`, `TRAFFIC_UNAWARE` and only distance/duration fields.
It returns miles and minutes with `simulated=False`; these are Google average
traffic-independent route estimates, not current traffic measurements. Routes
replaces legacy Distance Matrix by the owner's earlier decision (PR #64).

The owner approved the existing fixture fallback for #29: when Google cannot
provide a route, a matching synthetic home and fixture place ID may return the
fixture distance/time with `simulated=True` and a count-free warning. Real clinic
IDs or unrelated origins fail with a safe error. No driving time is invented from
straight-line distance, and live clinics are never silently swapped for fixture
clinics. Missing API credentials fail before network requests. The orchestrator
must preserve the simulated label when publishing discovery/distance events.

Validation: `python -m pytest -q integrations/tests/test_maps_live.py
integrations/tests/test_adapters_mock.py` covers typed results, units and order,
phone substitution and preflight, malformed details, sanitized vendor failures,
and restricted fixture fallback using fake HTTP. One live hand test found three
clinics, substituted three demo phones and obtained three driving routes; it sent
no calls or SMS. Exact command and outcome are in PR #74. Adapter signatures and
shared types are unchanged; no database writes or backend changes are required.

Vendor references: [Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search),
[Place Details](https://developers.google.com/maps/documentation/places/web-service/place-details),
[computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes).


## ElevenLabs outbound voice (#26)

`voice_elevenlabs.start_call(CallSpec) -> CallHandle` starts an outbound discovery
call in `VOICE_MODE=live`. It allowlists the destination before client creation
and again after read-only settings checks, immediately before the POST. The
backend must create the task/call rows before dialing (the proxy loads redacted
context by call_id), store `external_ref` from the returned conversation ID and
skip calls with a persisted receipt. A vendor acceptance is not a completed call,
Offer, booking or proof of dashboard delivery. Ambiguous POST failures are not
retried automatically; reconcile before any resubmission.

The adapter sends clinic name, care type, optional budget/carrier and ISO windows
as scalar dynamic variables. It sends call_id and LLM_PROXY_SECRET in
`custom_llm_extra_body`, not dynamic variables. It never sends the owner's record,
clinic street address, dropped field names/values or raw intake. No model ID is
hard-coded. The configured agent must use the expected PUBLIC_BASE_URL proxy.

Before every dial, GET checks require the agent's first message to begin with
`Hi, I'm an AI assistant calling for a patient.`, privacy.record_voice=false,
Custom LLM extra body enabled, and only transcript/call-failure webhook events.
The imported number must be Twilio, support outbound calls and be assigned to the
configured agent. The POST also sets call_recording_enabled=false. Nothing calls
an audio endpoint or stores audio. No settings are changed automatically. Errors
omit credentials, vendor messages and bodies; HTTP requests have bounded timeouts
and no redirects/retries. A changed/incomplete API configuration fails closed.
Webhook destination/secret correctness still requires the actual signed round
trip; settings presence alone is not that proof.

`VOICE_MODE=mock` delegates to `voice_mock` once #13 lands, using its existing
callback lifecycle and backend fixtures. If that separate adapter is not present,
standalone mock calls fail before network access; main's fixture mock pipeline
remains usable through its backend fallback. Unknown modes fail. No code from an
unmerged PR is copied or stacked here.

**Backend work needed:** main's build_deps still rejects VOICE_MODE=live. Joyce
must wire live starts off the server event loop, persist external_ref, wait for
the signed webhook's structured results and feed those facts into the pipeline.
Three starts may run concurrently; the fake-HTTP regression proves no adapter
serialization. The documented workspace limit is four, but a real three-call
run and current plan/minute availability have not been verified here.

`confirm_booking(CallSpec, slot) -> Confirmation` retains its signature but fails
before dialing in live mode. The current proxy prompt explicitly forbids booking
and its CallSpec has no approved booking intent/slot context. Joyce must add an
approval-aware booking flow and structured confirmation evidence before this
adapter can safely implement it; transcript wording is never a confirmation
receipt. The synchronous backend booking call must also run off the server loop.
Mock confirmation delegates to #13 and remains explicitly simulated.

Required existing settings: ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID,
ELEVENLABS_PHONE_NUMBER_ID, ELEVENLABS_WEBHOOK_SECRET, LLM_PROXY_SECRET,
PUBLIC_BASE_URL, and DEMO_PHONE_ALLOWLIST. `python-dotenv` is declared for the
read-only helper:

`python -m integrations.elevenlabs_preflight --env-file ../lifeline-6/.env`

The local run reported missing agent ID, phone-number ID and webhook secret.
No real call was placed, no live transcript/call_result was demonstrated and no
live booking receipt exists. PR #84 remains draft until account setup (#67),
backend live/booking support and the issue's live one-call/three-call acceptance
are complete. Exact tests and preflight outcome are in its body.

Vendor references: [Outbound call](https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call),
[Agent settings](https://elevenlabs.io/docs/api-reference/agents/get),
[Imported number](https://elevenlabs.io/docs/api-reference/phone-numbers/get).

## Live SMS (#27)

`SMS_MODE=live` retains `send(to_e164, text, idempotency_key)` and
`parse_inbound(form)`. Existing Twilio/PUBLIC_BASE_URL settings suffice; no new
variables are introduced. The send boundary checks DEMO_PHONE_ALLOWLIST before
constructing the client and immediately before submission. The configured sender
must be owned by the Twilio account and SMS-capable, as verified with a read-only
IncomingPhoneNumbers lookup. A verified voice caller ID alone is insufficient.
The adapter returns the accepted Message SID as a typed, non-simulated receipt;
queued/accepted is submission evidence, not proof of final delivery. Timeouts and
vendor failures return safe errors without logging response bodies or messages.
SDK request/response logging is disabled, timeouts are bounded and retries are off.

The backend still owns durable idempotency: persist the receipt under task+step
and skip sends whose receipt already exists. The adapter does not write database
state and does not claim that Twilio enforces the supplied idempotency key.
After an ambiguous timeout, reconcile the send before retrying; do not blindly
resubmit. No process-local cache is presented as durable deduplication.

For live inbound requests the backend route must build trusted context:

```python
from integrations.sms_inbound import SignedSMSForm
from integrations.sms_twilio import parse_inbound

incoming = parse_inbound(SignedSMSForm(
    parameters=await request.form(),  # entire form, no signature/role added to it
    signature=request.headers.get("X-Twilio-Signature", ""),
    roles=phone_to_role_from_backend_identity_store,
))
```

`roles` must come from backend-owned identity data, never request fields or an
inferred order in the allowlist. No identities are invented from fixture phones
in live mode. Configure Twilio to POST to
`PUBLIC_BASE_URL + /api/webhooks/twilio/sms`, with an HTTPS origin and no query
string. The signature is checked against that configured external URL (not an
untrusted forwarded host), including all form fields. Duplicate fields, unsigned
bare forms, unknown/unmapped senders, wrong account/recipient and media messages
are rejected. Media is never fetched or stored. A signed `task_id` is correlation
only; it does not authorize an approval or associate the sender with a task.

**Backend dependency:** Joyce's #22/#23 must wire the route, bind real identities,
check the waiting task state and scope, durably deduplicate MessageSid, invoke
approval/contact handling and return a fast 2xx/TwiML acknowledgement. The backend
must map signature/allowlist failures to rejection without exposing request data
or mutating task state. This PR never imports the backend or writes its files.
Main now has the approval webhook from #22, but it must wrap the actual request
header/form and backend identities in SignedSMSForm before live validation can
succeed. Bare live forms raise the RuntimeError its handler catches, returning a
safe ignored result. #7 / PR #79 separately records the live trial send/receive;
per the coordinator, #27 lands on code review and mock tests using that evidence,
without claiming the separate backend YES/contact workflow is complete.

Tests use synthetic forms, SDK signature generation and fake Twilio resources.
The read-only live preflight found that the configured sender does not meet the
owned/SMS-capable requirement. No real SMS was sent or received. Exact command
and sanitized result are in PR #76; successful live send and ngrok round trip
remain acceptance work after the account and backend dependencies are resolved.

References: [Twilio request validation](https://www.twilio.com/docs/usage/security),
[Messages resource](https://www.twilio.com/docs/messaging/api/message-resource).


D16 compatibility: SMS_MODE=mock continues to simulate outbound messages. A
trusted SignedSMSForm always uses live signature validation and returns a
non-simulated inbound fact, even with SMS_MODE=mock. This supports the decided
mock-outbound/live-inbound demo without sending custom trial SMS. A plain form
cannot supply trusted signature or role context. The new-style trial's classic
IncomingPhoneNumbers lookup result is not an outstanding #27 acceptance blocker:
Joyce's delivered/received evidence and its limitations are recorded in #7/PR #79.
The optional live outbound sender check remains strict; the demo keeps it off.


### One-call live acceptance command

Only after the backend owner prepares a fresh synthetic task/call with no result,
use `python -m integrations.elevenlabs_smoke --env-file ../lifeline-6/.env
--call-id <prepared-call-id> --allowlist-index <one-based-authorized-entry>`.
This is an explicitly live command, independent of the file's VOICE_MODE. It
uses the backend's redacted intake and windows and replaces only the fixture
clinic phone with the explicitly selected allowlisted teammate destination.
It refuses unknown clinics, missing/ambiguous contexts and already completed
calls. Never reuse a context after a partially successful or ambiguous dial.

The test checks Twilio read access before dialing, captures only this dial's
call-control receipt, and schedules a hangup after 60 seconds. It rechecks the
actual Twilio destination before call control. The teammate should also hang up
at the one-minute limit if call control reports a failure. Output contains only
receipt/status/count/disclosure checks, never phone numbers or transcript text.
No audio is fetched or stored; the adapter's recording-off preflight still runs.
An accepted dial is not a booking or proof of a complete offer. The command
succeeds only when transcript events and one structured call_result arrive.

The configured opening is spoken directly by ElevenLabs before the first proxy
reply. The smoke harness verifies disclosure against the vendor text transcript,
not the first backend-recorded generated reply. It reports only booleans/counts,
including interrupted turns and audio-storage flags. A hard duration limit may
cut off a closing sentence; finish the demo exchange before the cutoff.
