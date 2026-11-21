"""Live Maps boundaries exercised through fake HTTP, never real phones."""

import json
import logging

import httpx
import pytest

from integrations import google_distance as distance
from integrations import google_places as places
from integrations import maps_google_api as api
from integrations.fixtures import read_fixture
from integrations.types import Clinic

PHONES = ["+15555550121", "+15555550122", "+15555550123"]


@pytest.fixture(autouse=True)
def live_environment(monkeypatch):
    monkeypatch.setenv("PLACES_MODE", "live")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-only-key")
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", ",".join(PHONES))
    monkeypatch.setattr(
        httpx.Client, "send", lambda *a, **k: pytest.fail("Real HTTP forbidden")
    )


def install(monkeypatch, handler):
    original = api.MapsClient
    # Restore the real send only within MockTransport clients.
    from httpx import Client

    def request(self, method, url, **kwargs):
        request = self.build_request(method, url, **kwargs)
        return self._transport.handle_request(request)

    monkeypatch.setattr(Client, "request", request)
    monkeypatch.setattr(
        api, "MapsClient", lambda: original(transport=httpx.MockTransport(handler))
    )
    # Places imports its client once; distance imports it at the call boundary.
    from integrations import places_live

    monkeypatch.setattr(places_live, "MapsClient", api.MapsClient)


def detail(place_id):
    return {
        "id": place_id,
        "displayName": {"text": "Synthetic HTTP clinic"},
        "formattedAddress": "Example address",
        "internationalPhoneNumber": "+1 555 555 0199",
        "location": {"latitude": 41.9, "longitude": -87.6},
    }


def clinic(place_id="live-place"):
    return Clinic(
        name="Test",
        phone_e164=PHONES[0],
        address="Example",
        lat=41.9,
        lng=-87.6,
        place_id=place_id,
        simulated=True,
    )


def test_search_details_and_phone_substitution(monkeypatch, caplog):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["X-Goog-Api-Key"] == "test-only-key"
        assert "test-only-key" not in str(request.url)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "textQuery": "dental cleaning near Chicago, IL",
                "pageSize": 3,
            }
            assert request.headers["X-Goog-FieldMask"] == "places.id"
            return httpx.Response(
                200, json={"places": [{"id": str(i)} for i in range(3)]}
            )
        assert "internationalPhoneNumber" in request.headers["X-Goog-FieldMask"]
        return httpx.Response(200, json=detail(request.url.path.split("/")[-1]))

    install(monkeypatch, handler)
    with caplog.at_level(logging.INFO):
        results = places.find_clinics("dental cleaning", "Chicago, IL")
    assert len(requests) == 4
    assert [c.phone_e164 for c in results] == PHONES
    assert all(c.simulated and c.address == "Example address" for c in results)
    assert "substitution applied; clinics=3" in caplog.text
    assert all(phone not in caplog.text for phone in PHONES)
    assert "0199" not in caplog.text


@pytest.mark.parametrize(
    "allowlist", ["", ",".join(PHONES[:2]), ",".join([PHONES[0]] * 3), "bad,bad2,bad3"]
)
def test_allowlist_preflight_before_any_network(monkeypatch, allowlist):
    monkeypatch.setenv("DEMO_PHONE_ALLOWLIST", allowlist)
    with pytest.raises(RuntimeError, match="allowlist"):
        places.find_clinics("dental cleaning", "Chicago")


@pytest.mark.parametrize("value", [None, "", "555-0199"])
def test_missing_or_invalid_phone_never_returns_a_clinic(monkeypatch, value):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"places": [{"id": "one"}]})
        result = detail("one")
        result["internationalPhoneNumber"] = value
        return httpx.Response(200, json=result)

    install(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="international phone"):
        places.find_clinics("care", "city", 1)


def test_empty_search_and_zero_limit(monkeypatch):
    assert places.find_clinics("care", "city", 0) == []
    install(monkeypatch, lambda r: httpx.Response(200, json={}))
    assert places.find_clinics("care", "city") == []


@pytest.mark.parametrize(
    "mutation", ["missing_address", "mismatched_id", "bad_coordinates"]
)
def test_invalid_details_are_sanitized(monkeypatch, mutation):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"places": [{"id": "one"}]})
        result = detail("one")
        if mutation == "missing_address":
            del result["formattedAddress"]
        elif mutation == "mismatched_id":
            result["id"] = "other"
        else:
            result["location"]["latitude"] = 1000
        return httpx.Response(200, json=result)

    install(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="incomplete clinic details") as error:
        places.find_clinics("care", "city", 1)
    assert "Example address" not in str(error.value)


def test_routes_preserve_order_units_and_real_source(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        assert (
            str(request.url)
            == "https://routes.googleapis.com/directions/v2:computeRoutes"
        )
        body = json.loads(request.content)
        assert (
            body["travelMode"] == "DRIVE"
            and body["routingPreference"] == "TRAFFIC_UNAWARE"
        )
        assert body["origin"]["location"]["latLng"]["latitude"] == 41.8
        assert (
            request.headers["X-Goog-FieldMask"]
            == "routes.distanceMeters,routes.duration"
        )
        return httpx.Response(
            200,
            json={
                "routes": [{"distanceMeters": 1609.344 * count, "duration": "120.5s"}]
            },
        )

    install(monkeypatch, handler)
    results = distance.drive((41.8, -87.7), [clinic("second"), clinic("first")])
    assert [r.place_id for r in results] == ["second", "first"]
    assert [r.miles for r in results] == [1, 2]
    assert results[0].minutes == pytest.approx(120.5 / 60)
    assert all(not r.simulated for r in results)


def test_fixture_fallback_matches_origin_and_clinic(monkeypatch, caplog):
    install(
        monkeypatch,
        lambda r: httpx.Response(503, json={"error": "private vendor body"}),
    )
    monkeypatch.setenv("PLACES_MODE", "fixture")
    clinics = places.find_clinics("dental cleaning", "near home")
    monkeypatch.setenv("PLACES_MODE", "live")
    home = read_fixture("users.json")["owner"]["home"]
    results = distance.drive(home, clinics)
    assert [r.minutes for r in results] == [6, 4, 14]
    assert all(r.simulated for r in results)
    assert "simulated fixture" in caplog.text
    assert "private vendor body" not in caplog.text
    with pytest.raises(RuntimeError, match="no matching fixture"):
        distance.drive((40, -87), clinics)
    with pytest.raises(RuntimeError, match="no matching fixture"):
        distance.drive(home, [clinic()])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"routes": []},
        {"routes": [None]},
        {"routes": [{"duration": "bad"}]},
        {"routes": [{"distanceMeters": -1, "duration": "60s"}]},
    ],
)
def test_unusable_routes_fail_without_invented_times(monkeypatch, payload):
    install(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(RuntimeError, match="no matching fixture"):
        distance.drive((41, -87), [clinic()])


@pytest.mark.parametrize(
    "origin", [None, {}, (1000, 0), (True, 0), (float("nan"), 0), []]
)
def test_invalid_origin_rejected_before_network(origin):
    with pytest.raises(RuntimeError, match="origin"):
        distance.drive(origin, [clinic()])


@pytest.mark.parametrize("kind", ["http", "json", "timeout", "redirect"])
def test_vendor_errors_never_expose_response_or_key(monkeypatch, kind):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("sensitive body and key", request=request)
        if kind == "json":
            return httpx.Response(200, text="private invalid JSON")
        return httpx.Response(
            403 if kind == "http" else 302, text="private vendor body"
        )

    install(monkeypatch, handler)
    with pytest.raises(RuntimeError) as error:
        places.find_clinics("care", "city", 1)
    assert "private" not in str(error.value) and "sensitive" not in str(error.value)
    assert "test-only-key" not in str(error.value)


def test_missing_key_and_unknown_mode_fail_closed(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")
    with pytest.raises(RuntimeError, match="GOOGLE_MAPS_API_KEY"):
        places.find_clinics("care", "city", 1)
    monkeypatch.setenv("PLACES_MODE", "typo")
    for invoke in [
        lambda: places.find_clinics("care", "city"),
        lambda: distance.drive("home", []),
    ]:
        with pytest.raises(RuntimeError, match="PLACES_MODE"):
            invoke()
