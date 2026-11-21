"""Settings loaded from .env (see docs/ARCHITECTURE.md, Environment variables). No defaults for model IDs.

`load_settings()` reads the repo-root .env (never overriding real environment variables), builds a
`Settings`, and `Settings.validate_startup()` raises `MissingSetting` for every value a live adapter
needs but does not have. Model IDs are never invented: a missing ID is `None` until `require()` asks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

Mode = Literal["mock", "live"]
PlacesMode = Literal["fixture", "live"]
TransportMode = Literal["fixture"]
StreamMode = Literal["sse", "poll"]

# What each live adapter needs before the app may start. The human-readable key is the .env name.
LIVE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "voice": (
        "NVIDIA_API_KEY",
        "NEMOTRON_LIGHTNING_ID",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_AGENT_ID",
        "ELEVENLABS_PHONE_NUMBER_ID",
        "LLM_PROXY_SECRET",
        "PUBLIC_BASE_URL",
        "DEMO_PHONE_ALLOWLIST",
    ),
    "sms": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "PUBLIC_BASE_URL", "DEMO_PHONE_ALLOWLIST"),
    "calendar": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"),
    "places": ("GOOGLE_MAPS_API_KEY",),
}

MODEL_IDS: dict[str, str] = {
    "nano": "NEMOTRON_NANO_TAG",
    "lightning": "NEMOTRON_LIGHTNING_ID",
    "super": "NEMOTRON_SUPER_ID",
}


class MissingSetting(Exception):
    """A required .env value is empty. The message names every missing variable."""


class Settings(BaseModel):
    app_env: str = "development"
    app_timezone: str = "America/Chicago"
    database_url: str = "sqlite:///./lifeline.db"
    public_base_url: str | None = None
    llm_proxy_secret: str | None = None
    dashboard_session_secret: str | None = None

    nvidia_api_key: str | None = None
    nemotron_lightning_id: str | None = None
    nemotron_super_id: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    nemotron_nano_tag: str | None = None

    elevenlabs_api_key: str | None = None
    elevenlabs_agent_id: str | None = None
    elevenlabs_phone_number_id: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_refresh_token: str | None = None
    google_maps_api_key: str | None = None

    demo_phone_allowlist: tuple[str, ...] = Field(default_factory=tuple)

    voice_mode: Mode = "mock"
    places_mode: PlacesMode = "fixture"
    calendar_mode: Mode = "mock"
    sms_mode: Mode = "mock"
    transport_mode: TransportMode = "fixture"
    live_stream_mode: StreamMode = "sse"

    @property
    def modes(self) -> dict[str, str]:
        return {
            "voice": self.voice_mode,
            "places": self.places_mode,
            "calendar": self.calendar_mode,
            "sms": self.sms_mode,
            "transport": self.transport_mode,
            "live_stream": self.live_stream_mode,
        }

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def model_id(self, which: str) -> str | None:
        return getattr(self, MODEL_IDS[which].lower())

    def require(self, *env_names: str) -> None:
        """Raise MissingSetting naming every variable in `env_names` that is empty."""
        missing = [name for name in env_names if not getattr(self, name.lower())]
        if missing:
            raise MissingSetting(f"missing in .env: {', '.join(missing)}")

    def require_model(self, which: str) -> str:
        """Return the model ID for nano, lightning or super, or raise. Never a guessed default."""
        env_name = MODEL_IDS[which]
        self.require(env_name)
        return self.model_id(which)  # type: ignore[return-value]

    @property
    def any_live(self) -> bool:
        return any(mode == "live" for mode in self.modes.values())

    def validate_startup(self) -> None:
        """Raise MissingSetting when any adapter set to live lacks a value it needs.

        Any live adapter means the live pipeline runs, and that pipeline uses all three Nemotron models
        (Nano for intake, Lightning on the calls, Super for ranking; docs/DECISIONS.md D4), so every
        model ID must be set before the app may start.
        """
        missing: list[str] = []
        if not self.is_development and not self.dashboard_session_secret:
            missing.append("DASHBOARD_SESSION_SECRET")
        if self.any_live:
            missing += [name for name in MODEL_IDS.values() if not getattr(self, name.lower())]
        for adapter, needed in LIVE_REQUIREMENTS.items():
            if self.modes[adapter] == "live":
                missing += [name for name in needed if not getattr(self, name.lower())]
        if missing:
            raise MissingSetting("startup needs values that are empty in .env: " + ", ".join(dict.fromkeys(missing)))


def _env(name: str, env: dict[str, str]) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def load_settings(env_file: Path | None = ENV_FILE, environ: dict[str, str] | None = None) -> Settings:
    """Build Settings from `environ` (default: os.environ after loading `env_file`). Empty strings count as unset."""
    if environ is None:
        if env_file is not None and env_file.exists():
            load_dotenv(env_file, override=False)
        environ = dict(os.environ)
    values: dict[str, object] = {}
    for field_name in Settings.model_fields:
        raw = _env(field_name.upper(), environ)
        if raw is None:
            continue
        if field_name == "demo_phone_allowlist":
            values[field_name] = tuple(p.strip() for p in raw.split(",") if p.strip())
        else:
            values[field_name] = raw
    return Settings(**values)
