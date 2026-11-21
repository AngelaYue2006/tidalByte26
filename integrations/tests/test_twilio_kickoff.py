"""Read-only kickoff checks use synthetic fixtures; no network or messages."""

import unittest

from integrations.twilio_kickoff import CheckFailed, check


class TwilioKickoffTests(unittest.TestCase):
    def setUp(self):
        self.phones = ["+15555550101", "+15555550102", "+15555550103"]
        self.values = {
            "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TWILIO_AUTH_TOKEN": "synthetic-test-token",
            "TWILIO_PHONE_NUMBER": "+15555550100",
            "DEMO_PHONE_ALLOWLIST": ",".join(self.phones),
        }
        self.responses = {
            ".json": {"status": "active", "type": "Trial"},
            "/OutgoingCallerIds.json?PageSize=1000": {
                "outgoing_caller_ids": [{"phone_number": p} for p in self.phones]
            },
            "/IncomingPhoneNumbers.json?PageSize=1000": {
                "incoming_phone_numbers": [
                    {"phone_number": "+15555550100", "capabilities": {"sms": True}}
                ]
            },
        }

    def test_ready_only_with_verified_recipients_and_owned_sms_sender(self):
        results = check(self.values, self.responses.__getitem__)
        self.assertTrue(results["phone_setup_ready"])
        self.assertNotIn(self.values["TWILIO_AUTH_TOKEN"], str(results))
        for phone in self.phones:
            self.assertNotIn(phone, str(results))

    def test_bad_allowlist_is_not_ready(self):
        self.values["DEMO_PHONE_ALLOWLIST"] = "placeholder"
        self.assertFalse(
            check(self.values, self.responses.__getitem__)["phone_setup_ready"]
        )

    def test_unverified_recipient_is_not_ready(self):
        self.responses["/OutgoingCallerIds.json?PageSize=1000"][
            "outgoing_caller_ids"
        ].pop()
        self.assertFalse(
            check(self.values, self.responses.__getitem__)["phone_setup_ready"]
        )

    def test_unowned_sender_is_not_ready(self):
        self.values["TWILIO_PHONE_NUMBER"] = "+15555550199"
        self.assertFalse(
            check(self.values, self.responses.__getitem__)["phone_setup_ready"]
        )

    def test_invalid_credentials_do_not_call_api(self):
        self.values["TWILIO_ACCOUNT_SID"] = "placeholder"
        with self.assertRaises(CheckFailed):
            check(self.values, lambda path: self.fail("Must not access network"))


if __name__ == "__main__":
    unittest.main()
