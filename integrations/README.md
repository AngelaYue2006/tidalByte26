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

**Backend wiring is pending.** Main still has skeletons for the live proxy and
event bus. Proposed PR #58 defines `record_turn(engine, call_id, speaker, text)`;
PR #55 defines the event emitter. The simulator provides callback injection but
does not invent a new HTTP endpoint or import/write backend state. A backend
owner must supply the shared callback shim; a callback-spy test is not proof of
end-to-end dashboard delivery. Keep #13 draft/blocked until that acceptance is
verified against the landed backend callback.

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