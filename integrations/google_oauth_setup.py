"""Authorize the local demo Calendar account; save tokens only to an ignored .env.

python -m integrations.google_oauth_setup --env-file ../lifeline-6/.env
The user approves Google consent in their own browser. No events are created.
"""

import argparse
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values, set_key
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    # OAuth callback URLs contain authorization codes; suppress library HTTP logs.
    logging.disable(logging.CRITICAL)
    try:
        path = args.env_file.resolve(strict=True)
        if path.name != ".env":
            raise ValueError("Expected a local .env file")
        values = dotenv_values(path)
        client_id = values.get("GOOGLE_CLIENT_ID", "")
        client_secret = values.get("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.")
            return 1
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            },
            scopes=SCOPES,
            autogenerate_code_verifier=True,
        )
        print(
            "Opening Google consent. Choose the demo account and approve the two Calendar permissions.",
            flush=True,
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            authorization_prompt_message="",
            success_message="LifeLine authorization received. You may close this tab.",
            timeout_seconds=300,
            access_type="offline",
            prompt="consent select_account",
            include_granted_scopes="false",
        )
        granted = credentials.granted_scopes or credentials.scopes or []
        if set(granted) != set(SCOPES):
            print(
                "Consent did not grant exactly the requested Calendar scopes; token not saved."
            )
            return 1
        token = credentials.refresh_token
        if not token or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
            print("No usable refresh token returned; .env left unchanged.")
            return 1
        # set_key re-reads the current file, retaining unrelated settings such as Maps.
        set_key(str(path), "GOOGLE_REFRESH_TOKEN", token, quote_mode="never")
        print(
            "Refresh token saved to the local .env without displaying it.", flush=True
        )
        credentials.refresh(Request())
        print("Refresh-token exchange: succeeded.", flush=True)
        now = datetime.now(UTC)
        body = {
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=1)).isoformat(),
            "items": [{"id": "primary"}],
        }
        request = urllib.request.Request(
            "https://www.googleapis.com/calendar/v3/freeBusy",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + credentials.token,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        calendar = result.get("calendars", {}).get("primary", {})
        if calendar.get("errors") or "busy" not in calendar:
            print(
                "Free/busy query returned a calendar-level error; availability not verified."
            )
            return 1
        print(
            "Calendar free/busy query: succeeded. No event details printed or events created."
        )
        return 0
    except urllib.error.HTTPError as error:
        print("Calendar HTTP status:", error.code)
    except Exception as error:  # noqa: BLE001 - sanitize all credential failures
        # Exception text can expose callback URLs, tokens or calendar identifiers.
        print("OAuth setup stopped:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
