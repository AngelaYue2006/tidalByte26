"""T08_duplicate_webhook — see docs/MVP.md test matrix.

The receipts half (a repeated POST or step: one SMS, one booking, one calendar event) runs in
backend/tests/test_idempotency.py; the Twilio webhook half lands with the approval module (#22).
"""
