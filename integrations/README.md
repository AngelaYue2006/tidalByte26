# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
Calendar supports live mode as described below; other live service modes still fail closed. Voice implementations are
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