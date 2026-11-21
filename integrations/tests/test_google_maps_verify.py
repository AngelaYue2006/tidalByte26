"""Google Maps verification requires real result metrics, never credential output."""

from integrations import google_maps_verify as maps


def test_verification_requests_minimal_fields_and_hides_key(monkeypatch, capsys):
    def response(url, body, key, mask):
        assert key == "synthetic-key"
        if "places.googleapis.com" in url:
            assert mask == "places.id"
            return {"places": [{"id": "synthetic-place"}]}
        assert mask == "routes.distanceMeters,routes.duration"
        assert body["travelMode"] == "DRIVE"
        return {"routes": [{"distanceMeters": 1000, "duration": "120s"}]}

    monkeypatch.setattr(maps, "post_json", response)
    assert maps.verify("synthetic-key") == 0
    output = capsys.readouterr().out
    assert "synthetic-key" not in output
    assert "synthetic-place" not in output


def test_no_route_metrics_is_not_a_success(monkeypatch):
    monkeypatch.setattr(
        maps,
        "post_json",
        lambda url, *args: (
            {"places": [{"id": "synthetic-place"}]}
            if "places.googleapis.com" in url
            else {"routes": []}
        ),
    )
    assert maps.verify("synthetic-key") == 1
