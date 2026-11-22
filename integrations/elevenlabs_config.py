"""Local voice settings and read-only agent/number safety checks."""

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

OPENING_LINE = "Hi, I'm an AI assistant calling for a patient."


@dataclass(frozen=True, repr=False)
class VoiceSettings:
    api_key: str
    agent_id: str
    phone_id: str
    proxy_secret: str
    public_base_url: str

    @classmethod
    def load(cls):
        names = (
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_AGENT_ID",
            "ELEVENLABS_PHONE_NUMBER_ID",
            "LLM_PROXY_SECRET",
            "PUBLIC_BASE_URL",
            "ELEVENLABS_WEBHOOK_SECRET",
        )
        values = {name: os.getenv(name, "").strip() for name in names}
        missing = [name for name in names if not values[name]]
        if missing:
            raise RuntimeError("Live voice settings missing: " + ", ".join(missing))
        for name in ("ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID"):
            if not re.fullmatch(r"[A-Za-z0-9_-]+", values[name]):
                raise RuntimeError(name + " must be an ElevenLabs resource ID")
        base = values["PUBLIC_BASE_URL"].rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin")
        return cls(
            values["ELEVENLABS_API_KEY"],
            values["ELEVENLABS_AGENT_ID"],
            values["ELEVENLABS_PHONE_NUMBER_ID"],
            values["LLM_PROXY_SECRET"],
            base,
        )


def verify_agent(settings, agent):
    try:
        config = agent["conversation_config"]["agent"]
        platform = agent["platform_settings"]
        hooks = platform["workspace_overrides"]["webhooks"]
        llm = config["prompt"]
        expected = settings.public_base_url + "/v1"
        safe = (
            agent["agent_id"] == settings.agent_id
            and config["first_message"].startswith(OPENING_LINE)
            and platform["privacy"]["record_voice"] is False
            and platform["overrides"]["custom_llm_extra_body"] is True
            and llm["llm"] == "custom-llm"
            and llm["custom_llm"]["url"].rstrip("/")
            in {expected, expected + "/chat/completions"}
            and llm["custom_llm"].get("api_type", "chat_completions")
            == "chat_completions"
            and bool(hooks["post_call_webhook_id"])
            and isinstance(hooks["events"], list)
            and set(hooks["events"]) == {"transcript", "call_initiation_failure"}
            and hooks.get("send_audio") is not True
            and hooks.get("exclude_transcript") is not True
        )
    except (KeyError, TypeError, AttributeError):
        safe = False
    if not safe:
        raise RuntimeError(
            "ElevenLabs agent preflight failed: verify AI disclosure, audio off, "
            "custom proxy/extra body and text-only post-call webhooks"
        )


def verify_phone(settings, number):
    try:
        safe = (
            number["phone_number_id"] == settings.phone_id
            and number["provider"] == "twilio"
            and number.get("supports_outbound", True) is True
            and number["assigned_agent"]["agent_id"] == settings.agent_id
        )
    except (KeyError, TypeError):
        safe = False
    if not safe:
        raise RuntimeError(
            "ElevenLabs phone preflight failed: check imported Twilio number and agent assignment"
        )
