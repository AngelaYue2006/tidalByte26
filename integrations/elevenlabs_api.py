"""Small ElevenLabs HTTP boundary. Never fetches or stores audio."""

import httpx

from integrations.elevenlabs_config import VoiceSettings, verify_agent, verify_phone


class ElevenLabsClient:
    def __init__(self, transport=None):
        self.settings = VoiceSettings.load()
        self._http = httpx.Client(
            base_url="https://api.elevenlabs.io/v1/convai/",
            headers={"xi-api-key": self.settings.api_key},
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()

    def request(self, method, path, body=None):
        try:
            response = self._http.request(method, path, json=body)
            if response.status_code != 200:
                raise RuntimeError(
                    f"ElevenLabs request failed (HTTP {response.status_code}); call outcome unverified"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Invalid response")
            return data
        except (httpx.HTTPError, ValueError, TypeError):
            raise RuntimeError(
                "ElevenLabs request failed or returned invalid JSON; call outcome unverified"
            ) from None

    def preflight(self):
        verify_agent(
            self.settings, self.request("GET", "agents/" + self.settings.agent_id)
        )
        verify_phone(
            self.settings,
            self.request("GET", "phone-numbers/" + self.settings.phone_id),
        )
