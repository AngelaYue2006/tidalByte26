"""Google Calendar HTTP boundary, with fixed OAuth scopes and sanitized failures."""

import os

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from requests import Session

SCOPES = (
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
)


def access_token() -> str:
    names = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    values = {name: os.getenv(name, "") for name in names}
    if missing := [name for name, value in values.items() if not value]:
        raise RuntimeError("Calendar credentials missing: " + ", ".join(missing))
    try:
        credentials = Credentials(
            token=None,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
            client_id=values["GOOGLE_CLIENT_ID"],
            client_secret=values["GOOGLE_CLIENT_SECRET"],
            refresh_token=values["GOOGLE_REFRESH_TOKEN"],
        )
        with Session() as session:
            credentials.refresh(Request(session=session))
        if not credentials.token:
            raise ValueError("No access token returned")
        return credentials.token
    except Exception:  # noqa: BLE001 - vendor exceptions can contain credential values
        raise RuntimeError(
            "Calendar authentication failed; check Google credentials"
        ) from None


class CalendarClient:
    """One client per adapter call; no shared mutable credentials or database state."""

    def __init__(self, *, transport=None):
        token = access_token()
        self._http = httpx.Client(
            base_url="https://www.googleapis.com/calendar/v3/",
            timeout=25,
            transport=transport,
            follow_redirects=False,
            headers={"Authorization": "Bearer " + token},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()

    def _request(self, method, path, **kwargs):
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise RuntimeError(
                "Calendar request failed; retry with the same idempotency key"
            ) from None

    @staticmethod
    def _json(response):
        if not response.is_success:
            raise RuntimeError(f"Calendar request failed (HTTP {response.status_code})")
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise TypeError("Expected an object")
            return result
        except (ValueError, TypeError):
            raise RuntimeError("Calendar returned an invalid response") from None

    def free_busy(self, body):
        return self._json(self._request("POST", "freeBusy", json=body))

    def insert_event(self, body):
        response = self._request(
            "POST",
            "calendars/primary/events",
            json=body,
            params={"sendUpdates": "none"},
        )
        return None if response.status_code == 409 else self._json(response)

    def get_event(self, event_id):
        return self._json(self._request("GET", f"calendars/primary/events/{event_id}"))
