# Shared contracts

JSON Schemas that the backend emits and the frontend consumes. Change only by PR reviewed by the affected owners, together with `docs/ARCHITECTURE.md`.

- `events.schema.json` — every dashboard event (see Live events in the architecture doc).
- `intake_request.schema.json` — the redacted `IntakeRequest` that is the only thing allowed to leave the device.
- `decision.schema.json` — Nemotron Super's ranking output.
- `task.schema.json` — task projection returned by `GET /api/tasks/{id}`, with owner and contact variants.
