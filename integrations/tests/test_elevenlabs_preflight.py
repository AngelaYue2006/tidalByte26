"""Read-only preflight CLI protects local credentials and never initiates calls."""

from integrations import elevenlabs_preflight as preflight


def test_preflight_refuses_non_env_file(tmp_path, capsys):
    example = tmp_path / ".env.example"
    example.write_text("")
    assert preflight.main(["--env-file", str(example)]) == 1
    assert "existing local .env" in capsys.readouterr().out


def test_preflight_checks_settings_without_outbound(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    path.write_text("")
    checked = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def preflight(self):
            checked.append(True)

    monkeypatch.setattr(preflight, "ElevenLabsClient", Client)
    assert preflight.main(["--env-file", str(path)]) == 0
    assert checked == [True] and "no call placed" in capsys.readouterr().out


def test_preflight_does_not_print_unexpected_exception_contents(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / ".env"
    path.write_text("")

    def fail():
        raise ValueError("private-token-and-account")

    monkeypatch.setattr(preflight, "ElevenLabsClient", fail)
    assert preflight.main(["--env-file", str(path)]) == 1
    output = capsys.readouterr().out
    assert "ValueError" in output and "private-token-and-account" not in output
