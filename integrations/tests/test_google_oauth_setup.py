"""OAuth setup preserves local settings and never prints credential material."""

import io
import json
import sys
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from integrations import google_oauth_setup as setup


@pytest.fixture
def consent(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "GOOGLE_CLIENT_ID=synthetic-client\n"
        "GOOGLE_CLIENT_SECRET=synthetic-secret\n"
        "GOOGLE_REFRESH_TOKEN=old-synthetic-token\n"
        "GOOGLE_MAPS_API_KEY=keep-this-synthetic-key\n"
    )
    monkeypatch.setattr(sys, "argv", ["oauth-setup", "--env-file", str(path)])
    credentials = SimpleNamespace(
        granted_scopes=setup.SCOPES,
        scopes=setup.SCOPES,
        refresh_token="synthetic-refresh-token",
        token="synthetic-access-token",
        refresh=lambda request: None,
    )

    def factory(config, scopes, autogenerate_code_verifier):
        assert scopes == setup.SCOPES
        assert autogenerate_code_verifier
        return SimpleNamespace(run_local_server=lambda **kwargs: credentials)

    monkeypatch.setattr(setup.InstalledAppFlow, "from_client_config", factory)
    monkeypatch.setattr(
        setup.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps({"calendars": {"primary": {"busy": []}}}).encode()
        ),
    )
    return path, credentials


def test_success_preserves_other_settings_and_hides_tokens(consent, capsys):
    path, _ = consent
    assert setup.main() == 0
    values = dotenv_values(path)
    assert values["GOOGLE_REFRESH_TOKEN"] == "synthetic-refresh-token"
    assert values["GOOGLE_MAPS_API_KEY"] == "keep-this-synthetic-key"
    output = capsys.readouterr().out
    assert "free/busy query: succeeded" in output
    for secret in values.values():
        assert secret not in output


def test_partial_consent_does_not_overwrite_token(consent):
    path, credentials = consent
    credentials.granted_scopes = [setup.SCOPES[0]]
    assert setup.main() == 1
    assert dotenv_values(path)["GOOGLE_REFRESH_TOKEN"] == "old-synthetic-token"


def test_no_refresh_token_does_not_overwrite_token(consent):
    path, credentials = consent
    credentials.refresh_token = None
    assert setup.main() == 1
    assert dotenv_values(path)["GOOGLE_REFRESH_TOKEN"] == "old-synthetic-token"


def test_oauth_exception_text_is_not_printed(consent, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ValueError("sensitive-callback-code-and-token")

    monkeypatch.setattr(setup.InstalledAppFlow, "from_client_config", fail)
    assert setup.main() == 1
    assert "sensitive-callback-code-and-token" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["refresh", "http", "calendar"])
def test_failed_verification_preserves_existing_token(
    consent, monkeypatch, capsys, failure
):
    path, credentials = consent
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive-refresh-or-calendar-failure")

    if failure == "refresh":
        credentials.refresh = fail
    elif failure == "http":
        monkeypatch.setattr(setup.urllib.request, "urlopen", fail)
    else:
        monkeypatch.setattr(
            setup.urllib.request,
            "urlopen",
            lambda *a, **k: io.BytesIO(
                json.dumps(
                    {"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}}
                ).encode()
            ),
        )
    assert setup.main() == 1
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert "saved to the local" not in output
    assert "sensitive-refresh-or-calendar-failure" not in output
