# Fixtures (synthetic only)

- `users.json` — Mary Johnson (owner) and Sarah (contact, daughter). Fake phone numbers until replaced by allowlisted teammate numbers in `.env`. `owner` carries the full record Nano sees on device (home, DOB, insurance member ID, all synthetic); `contacts[]` mirrors the `contacts` table.
- `clinics.json` — three clinics with name, fake phone, address, lat/lng, distance_mi, drive_min. Used when `PLACES_MODE=fixture`. Each has an `id` that `receptionists.json` joins on.
- `free_windows.json` — Mary's free windows for the demo week. Used when `CALENDAR_MODE=mock`.
- `receptionists.json` — scripted replies per clinic for `VOICE_MODE=mock`: `status_changes` and transcript `lines` with `at_ms` timing, the structured `result` (price, slot, insurance) and the `booking_reply` for the confirm step. Status comes from `result`, never from the lines. Lines follow the prototype SCENARIO with the product rules applied: the agent discloses it is an AI on every call, speaks only redacted facts (never the owner's name) and never asks to hold or book a slot before approval.
- `past_runs.json` — two finished runs that `POST /api/demo/reset` seeds for the history page (T12): the request, windows, the three offers, the pick, booking, transport and ride, in the past two weeks. `app/seed.py` writes them as the pipeline would.
- `intake_utterances.jsonl` — 20 utterances with expected `IntakeRequest` and expected `dropped_fields`, for the redaction metric.

Every phone number is in the reserved fictional `+1 555-01xx` range. No real person, address or insurance ID anywhere.
