# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
Calendar, Places and distance support live mode as described below. SMS live
mode still fails closed on this branch. Voice implementations are separate
work (#13 and #26).

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

`parse_inbound(form)` supports only mock mode. `From` must pass
`DEMO_PHONE_ALLOWLIST` and match a synthetic owner/contact in `users.json`.
`MessageSid` and `Body` are required; optional `task_id` is returned as correlation
metadata, never proof that a task is waiting. The backend must match the sender
and waiting task before applying an approval or contact response. Fixture phones
must be explicitly allowlisted for mock SMS too; there is no safety bypass.

Mock inbound messages are marked simulated and are not authenticated Twilio
webhooks. Live mode fails closed; signature verification, real sender mapping and
live round-trip verification belong to #27. Do not expose mock parsing as a
trusted public webhook.

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
