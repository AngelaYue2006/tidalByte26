# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
Places and distance support live Google Maps requests as described below. Other
live service modes raise before a network request on this branch. Voice
implementations are separate work (#13 and #26).

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


## Live discovery and driving distances (#29)

Set `PLACES_MODE=live` and `GOOGLE_MAPS_API_KEY` in the backend environment.
Enable Places API (New) and Routes API for that key. Text Search sends only
`<care_type> near <area>` with a `places.id` field mask; Place Details requests
only name, address, coordinates and international phone. The live limit is 0?3;
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
