"""Read-only Twilio kickoff checks; never print secrets or phone numbers.

Run from the repository root:
python -m integrations.twilio_kickoff --env-file ../lifeline-6/.env
"""

import argparse
import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


class CheckFailed(Exception):
    """A sanitized setup or API failure."""


def read_settings(path):
    """Read literal KEY=value settings without executing shell expressions."""
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            closing = value.find(quote, 1)
            if closing < 0:
                raise CheckFailed("Unclosed quote in .env")
            value = value[1:closing]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key.strip()] = value
    return values


def e164(value):
    return bool(re.fullmatch(r"\+[1-9]\d{7,14}", value))


def check(values, fetch):
    """Fetch only account and phone configuration; return non-sensitive results."""
    sid = values.get("TWILIO_ACCOUNT_SID", "")
    token = values.get("TWILIO_AUTH_TOKEN", "")
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid) or not token:
        raise CheckFailed("Set a valid TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
    recipients = [
        item.strip()
        for item in values.get("DEMO_PHONE_ALLOWLIST", "").split(",")
        if item.strip()
    ]
    sender = values.get("TWILIO_PHONE_NUMBER", "")
    account = fetch(".json")
    verified = fetch("/OutgoingCallerIds.json?PageSize=1000")
    owned = fetch("/IncomingPhoneNumbers.json?PageSize=1000")
    if verified.get("next_page_uri") or owned.get("next_page_uri"):
        raise CheckFailed("Phone lists exceed one page; review them in Twilio Console")
    verified_phones = {
        item["phone_number"] for item in verified.get("outgoing_caller_ids", [])
    }
    owned_numbers = owned.get("incoming_phone_numbers", [])
    matches = [item for item in owned_numbers if item.get("phone_number") == sender]
    owned_phones = {item["phone_number"] for item in owned_numbers}
    recipient_matches = sum(
        phone in verified_phones or phone in owned_phones for phone in recipients
    )
    results = {
        "authentication": "succeeded",
        "account_active": account.get("status") == "active",
        "trial_account": account.get("type") == "Trial",
        "allowlist_entries": len(recipients),
        "allowlist_format_valid": bool(recipients) and all(map(e164, recipients)),
        "allowlist_entries_unique": len(set(recipients)) == len(recipients),
        "verified_recipients": recipient_matches,
        "sender_format_valid": e164(sender),
        "sender_owned": bool(matches),
        "sender_sms_capable": bool(
            matches and matches[0].get("capabilities", {}).get("sms")
        ),
    }
    ready = (
        results["account_active"]
        and results["allowlist_format_valid"]
        and results["allowlist_entries_unique"]
        and len(recipients) >= 3
        and (not results["trial_account"] or recipient_matches == len(recipients))
        and results["sender_format_valid"]
        and results["sender_owned"]
        and results["sender_sms_capable"]
    )
    results["phone_setup_ready"] = bool(ready)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = read_settings(args.env_file)
        sid = values.get("TWILIO_ACCOUNT_SID", "")
        credentials = sid + ":" + values.get("TWILIO_AUTH_TOKEN", "")
        authorization = "Basic " + base64.b64encode(credentials.encode()).decode()

        def fetch(path):
            request = urllib.request.Request(
                "https://api.twilio.com/2010-04-01/Accounts/" + sid + path,
                headers={"Authorization": authorization},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)

        results = check(values, fetch)
        print(json.dumps(results, indent=2))
        return 0 if results["phone_setup_ready"] else 1
    except urllib.error.HTTPError as error:
        print("Twilio API HTTP status:", error.code)
    except CheckFailed as error:
        print(str(error))
    except Exception as error:
        # URLs, exception bodies and account responses can contain private values.
        print("Setup check failed:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
