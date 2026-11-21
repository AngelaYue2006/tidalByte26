"""Nemotron Lightning as the live call agent. Builds the per-call system prompt and streams chat completions from the NVIDIA API. Used by routers.llm_proxy.

`LightningClient` is the real NVIDIA client; anything with the same `stream_chat` shape is a fake for
tests and for VOICE_MODE=mock. `relay` turns a chunk stream into the SSE bytes ElevenLabs expects and
reports the first-token latency and the agent's full sentence when the stream ends.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Protocol

from app.nemotron.prompts import call_agent
from app.nemotron.types import CallSpec

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MAX_REPLY_TOKENS = 120  # a phone turn is one or two sentences
TEMPERATURE = 0.3


class ChatStream(Protocol):
    """Yields OpenAI chat.completion.chunk dicts for one turn."""

    def stream_chat(self, messages: list[dict]) -> Iterator[dict]: ...


class LightningClient:
    """Nemotron Lightning through the OpenAI-compatible NVIDIA API. The model ID comes from .env via settings.require_model."""

    def __init__(self, api_key: str, model_id: str, base_url: str = NVIDIA_BASE_URL, timeout: float = 20.0) -> None:
        if not model_id:
            raise ValueError("NEMOTRON_LIGHTNING_ID is empty; set it in .env, never guess a model ID")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is empty")
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def stream_chat(self, messages: list[dict]) -> Iterator[dict]:
        stream = self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            stream=True,
            temperature=TEMPERATURE,
            max_tokens=MAX_REPLY_TOKENS,
        )
        for chunk in stream:
            yield chunk.model_dump(exclude_none=True)


def build_messages(spec: CallSpec, incoming: list[dict]) -> list[dict]:
    """Our system prompt first, then the conversation ElevenLabs sent, minus any system prompt of its own."""
    return [{"role": "system", "content": call_agent(spec)}] + [
        {"role": m["role"], "content": m.get("content") or ""} for m in incoming if m.get("role") != "system"
    ]


def delta_text(chunk: dict) -> str:
    try:
        return chunk["choices"][0]["delta"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def relay(
    chunks: Iterator[dict],
    *,
    on_first_token: Callable[[float], None] | None = None,
    on_complete: Callable[[str], None] | None = None,
) -> Iterator[bytes]:
    """SSE lines for ElevenLabs: `data: {chunk}` per chunk, then `data: [DONE]`. Times the first token, collects the sentence."""
    started = time.perf_counter()
    first_seen = False
    text: list[str] = []
    for chunk in chunks:
        piece = delta_text(chunk)
        if piece and not first_seen:
            first_seen = True
            if on_first_token:
                on_first_token(time.perf_counter() - started)
        text.append(piece)
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
    yield b"data: [DONE]\n\n"
    if on_complete:
        on_complete("".join(text).strip())


def collect(chunks: Iterator[dict]) -> tuple[str, dict | None]:
    """Non-streaming fallback: the whole reply and the last chunk (for id and model)."""
    text: list[str] = []
    last: dict | None = None
    for chunk in chunks:
        text.append(delta_text(chunk))
        last = chunk
    return "".join(text).strip(), last
