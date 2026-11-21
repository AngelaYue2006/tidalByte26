# Mock adapter handoff (#14)

Calendar, Places, distance, SMS and transport expose the existing signatures from
`docs/ARCHITECTURE.md`. All results are Pydantic facts from `integrations.types`.
SMS supports live mode as described below. Other live service modes fail closed
on this branch. Voice implementations are separate work (#13 and #26).

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
The route in main remains a stub, so an actual YES/contact round trip is not yet
verified and this PR stays draft/blocked. #7 also needs an owned SMS-capable sender.

Tests use synthetic forms, SDK signature generation and fake Twilio resources.
The read-only live preflight found that the configured sender does not meet the
owned/SMS-capable requirement. No real SMS was sent or received. Exact command
and sanitized result are in PR #76; successful live send and ngrok round trip
remain acceptance work after the account and backend dependencies are resolved.

References: [Twilio request validation](https://www.twilio.com/docs/usage/security),
[Messages resource](https://www.twilio.com/docs/messaging/api/message-resource).
