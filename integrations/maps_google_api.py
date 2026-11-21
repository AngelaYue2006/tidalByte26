"""Small Google Maps HTTP boundary; credentials and vendor bodies stay private."""

import os

import httpx


class MapsError(RuntimeError):
    """A sanitized vendor failure, eligible for the documented route fallback."""


class MapsClient:
    def __init__(self, transport=None):
        key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is required for live discovery")
        self._client = httpx.Client(
            headers={"X-Goog-Api-Key": key},
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def request(self, method, url, fields, body=None):
        try:
            response = self._client.request(
                method,
                url,
                headers={"X-Goog-FieldMask": fields},
                json=body,
            )
            if response.status_code != 200:
                raise MapsError(
                    f"Google Maps request failed (HTTP {response.status_code})"
                )
            data = response.json()
            if not isinstance(data, dict) or "error" in data:
                raise MapsError("Google Maps returned an invalid response")
            return data
        except (httpx.HTTPError, ValueError):
            raise MapsError(
                "Google Maps request failed or returned invalid JSON"
            ) from None
