"""Calendar HTTP/OAuth boundary: fixed scopes, sanitized failures and duplicate handling."""

import httpx
import pytest

from integrations import calendar_google_api as api


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "synthetic-credential")


def test_oauth_refresh_uses_only_required_scopes(monkeypatch):
    seen = {}

    class FakeCredentials:
        token = None

        def __init__(self, **kwargs):
            seen.update(kwargs)

        def refresh(self, request):
            self.token = "synthetic-access-token"

    monkeypatch.setattr(api, "Credentials", FakeCredentials)
    assert api.access_token() == "synthetic-access-token"
    assert set(seen["scopes"]) == {
        "https://www.googleapis.com/auth/calendar.freebusy",
        "https://www.googleapis.com/auth/calendar.events",
    }
    assert seen["token_uri"] == "https://oauth2.googleapis.com/token"


def test_missing_credentials_and_auth_failure_are_safe(monkeypatch):
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN")
    with pytest.raises(RuntimeError, match="GOOGLE_REFRESH_TOKEN"):
        api.access_token()
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "synthetic-credential")

    def fail(**kwargs):
        raise ValueError("synthetic-credential must not escape")

    monkeypatch.setattr(api, "Credentials", fail)
    with pytest.raises(RuntimeError, match="authentication failed") as error:
        api.access_token()
    assert "synthetic-credential" not in str(error.value)


def test_google_requests_use_bearer_header_and_no_invites(monkeypatch):
    monkeypatch.setattr(api, "access_token", lambda: "synthetic-access-token")
    seen = []

    def respond(request):
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        if request.url.path.endswith("/events"):
            assert request.url.params["sendUpdates"] == "none"
            return httpx.Response(
                409, json={"error": {"message": "synthetic-private-value"}}
            )
        return httpx.Response(200, json={"id": "synthetic-event"})

    with api.CalendarClient(transport=httpx.MockTransport(respond)) as client:
        assert client.insert_event({"id": "synthetic-event"}) is None
        assert client.get_event("synthetic-event")["id"] == "synthetic-event"
    assert [request.method for request in seen] == ["POST", "GET"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"error": {"message": "synthetic-private-value"}}),
        httpx.Response(200, text="not JSON"),
        httpx.Response(200, json=[]),
    ],
)
def test_vendor_errors_are_sanitized(monkeypatch, response):
    monkeypatch.setattr(api, "access_token", lambda: "synthetic-access-token")
    with (
        api.CalendarClient(
            transport=httpx.MockTransport(lambda request: response)
        ) as client,
        pytest.raises(RuntimeError, match="Calendar") as error,
    ):
        client.free_busy({})
    assert "synthetic-private-value" not in str(error.value)


def test_network_failure_does_not_leak_url_or_token(monkeypatch):
    monkeypatch.setattr(api, "access_token", lambda: "synthetic-access-token")

    def timeout(request):
        raise httpx.ReadTimeout("synthetic-access-token")

    with (
        api.CalendarClient(transport=httpx.MockTransport(timeout)) as client,
        pytest.raises(RuntimeError, match="same idempotency key") as error,
    ):
        client.insert_event({})
    assert "synthetic-access-token" not in str(error.value)
