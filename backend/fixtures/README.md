# Fixtures (synthetic only)

- `users.json` — Mary Johnson (owner) and Sarah (contact, daughter). Fake phone numbers until replaced by allowlisted teammate numbers in `.env`.
- `clinics.json` — three clinics with name, fake phone, address, lat/lng, distance_mi, drive_min. Used when `PLACES_MODE=fixture`.
- `free_windows.json` — Mary's free windows for the demo week. Used when `CALENDAR_MODE=mock`.
- `receptionists.json` — scripted replies per clinic for `VOICE_MODE=mock`: price, slot, insurance.
- `intake_utterances.jsonl` — 20 utterances with expected `IntakeRequest` and expected `dropped_fields`, for the redaction metric.
