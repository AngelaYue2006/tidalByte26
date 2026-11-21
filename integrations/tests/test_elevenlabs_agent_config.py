"""Issue #6: the agent placeholder opens with the AI disclosure, and the ElevenLabs env vars are documented with no values."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT = (ROOT / "integrations" / "elevenlabs_agent_prompt.md").read_text()
ENV_EXAMPLE = (ROOT / ".env.example").read_text().splitlines()


def test_first_message_is_the_ai_disclosure():
    section = PROMPT.split("## First message", 1)[1].split("##", 1)[0].strip()
    assert section == "Hi, I'm an AI assistant calling for a patient."


def test_system_prompt_forbids_booking_and_identifiers():
    system = PROMPT.split("## System prompt", 1)[1].split("##", 1)[0].lower()
    assert "you always say you are an ai" in system
    for banned in ("name", "date of birth", "member id", "address", "phone number", "symptoms", "medications"):
        assert banned in system, banned
    assert "do not book, hold or reserve" in system


def test_elevenlabs_env_vars_are_documented_without_values():
    names = {"ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID", "ELEVENLABS_WEBHOOK_SECRET"}
    seen = {}
    for line in ENV_EXAMPLE:
        key, _, rest = line.partition("=")
        if key in names:
            seen[key] = rest.split("#", 1)[0].strip()
    assert set(seen) == names
    assert all(value == "" for value in seen.values()), seen


def test_prompt_never_subscribes_to_audio():
    assert "Never `post_call_audio`" in PROMPT
    assert "call_recording_enabled: false" in PROMPT
