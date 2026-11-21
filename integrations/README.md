# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
Live service modes raise before any network request. Voice implementations are
separate work (#13 and #26); this PR defines their types only.

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
