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
