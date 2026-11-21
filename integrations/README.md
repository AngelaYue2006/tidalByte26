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

## Scripted receptionists (#13)

The mock keeps `voice_mock.start_call(call: CallSpec) -> CallHandle` and
`voice_mock.confirm_booking(call: CallSpec, slot) -> Confirmation`. Both enforce
`VOICE_MODE=mock` and `DEMO_PHONE_ALLOWLIST`, including for synthetic fixtures.
No phone is dialed. Use explicit synthetic numbers in the process allowlist for
local fixture tests; production/demo allowlists remain in the ignored `.env`.

Bind a backend-owned callback around a pipeline run:

```python
async with voice_mock.callbacks(emit_voice_event) as session:
    handles = [voice_mock.start_call(spec) for spec in call_specs]
    offers = await asyncio.gather(*(session.wait_call(h) for h in handles))
```

`emit_voice_event(event)` receives the schema-shaped `call_status`, `transcript`
and `call_result` dictionaries, each with `call_id` and `simulated: true`. It may
be synchronous or asynchronous. The backend shim must route transcript turns
through the same common recorder as the live proxy, attach the task and proper
viewer visibility, and publish each event once. `events.emit` expects type
separate from the payload, so the shim removes `type` before passing that payload.
Do not have both the recorder and shim emit the same transcript twice.

**Shared live-proxy callback acceptance is pending.** The event bus (#55) and
orchestrator bridge (#75) are now on main. The merged bridge uses this simulator
when present, and the combined pipeline tests pass with it. The live proxy's
common recorder remains in open PR #58 (`record_turn(engine, call_id, speaker,
text)`). The simulator does not invent an HTTP endpoint or import/write backend
state. A backend owner must route both mock and live transcripts through that
same recorder and verify it after #58 lands. Keep #13 draft/blocked until this
remaining acceptance is verified; the merged mock bridge alone does not prove
that live and mock share their recorder.

`start_call` returns immediately and schedules timed playback; the context exits
only after playback finishes, or cancels pending tasks on failure/cancellation.
The returned offer comes from structured fixture results, never transcript text.
`slotOk` checks full slot containment in the supplied free windows. Clinic
identity is matched by fixture place ID, not phone, so a safe teammate-number
substitution can retain the same script. Unknown scripts and missing first-agent
AI disclosures fail before any events. Timing follows fixture `at_ms` values,
including the longer hold. All three calls share the event loop and overlap.

Within one session, an identical call-ID/spec retry reuses its task and handle;
a conflicting specification fails. Persisted receipts and idempotency across
process/session restarts remain the backend's responsibility. Callback failures
propagate through `wait_call` or context exit. Nested async contexts keep separate
callbacks and task registries.

Booking reads the fixture's structured `booking_reply` and only accepts the
offered slot (label, aware ISO timestamp, Window or start/end mapping). Bright
Smile/Smile Co. produce simulated confirmed receipts; Oak Dental produces the
simulated tentative T7 variant without a confirmation reference. This method
returns synthetic facts only; the backend must enforce the approval gate and
never create a calendar event for tentative results.

`python -m pytest -q integrations/tests/test_voice_mock.py` includes one real-time
fixture test (about 15 seconds), plus fast callback, retry, allowlist, disclosure,
slot-match, cancellation and tentative-receipt regressions. External networking
is forbidden; Windows asyncio's internal loopback socket pair is allowed.
