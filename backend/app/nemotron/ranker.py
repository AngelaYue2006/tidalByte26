"""Nemotron Super. rank(offers, windows, priority) -> Decision JSON {winner_call_id, score, reasons, second, tradeoff, ranked}. Also summarize_call(transcript) -> CallResult when data collection is incomplete.

Super chooses the winner, scores every survivor and writes the trade-off sentence. The reason chips are
computed here from the same offer facts so they never drift from the numbers on the cards. The model's
reply is parsed strictly, checked against shared/decision.schema.json and the offer list, and asked
for once more on failure. summarize_call belongs to #21 and is not here yet.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator

from app import metrics
from app.nemotron.call_agent import NO_THINK_EXTRA_BODY
from app.nemotron.rank_prompt import (
    RANKING_SYSTEM,
    ranking_user_message,
    retry_user_message,
)
from app.ranking import OfferLike, WindowLike, money, slot_label

DECISION_SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "shared" / "decision.schema.json").read_text())
_validator = Draft202012Validator(DECISION_SCHEMA)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class RankingError(Exception):
    """Super did not return a usable Decision after one retry."""


class BadReply(ValueError):
    """One reply from Super could not be used; the message says why and goes into the retry prompt."""


class ChatJSON(Protocol):
    """One JSON-object completion. Implemented by NvidiaChatClient and by test fakes."""

    def complete_json(self, system: str, user: str, *, previous: list[dict] | None = None) -> str: ...


class NvidiaChatClient:
    """Nemotron Super through the OpenAI-compatible NVIDIA API. The model ID comes from .env via the caller."""

    def __init__(self, api_key: str, model_id: str, base_url: str = NVIDIA_BASE_URL, timeout: float = 30.0) -> None:
        if not model_id:
            raise ValueError("NEMOTRON_SUPER_ID is empty; set it in .env, never guess a model ID")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is empty")
        from openai import OpenAI

        self.model_id = model_id
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def complete_json(self, system: str, user: str, *, previous: list[dict] | None = None) -> str:
        messages = [{"role": "system", "content": system}, *(previous or []), {"role": "user", "content": user}]
        # Thinking off, as for Lightning: with it on, Super 3.5 spends the whole token budget in `reasoning_content`
        # and `content` comes back empty (finish_reason "length"), which read as "not valid JSON at char 0" (#92).
        reply = self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            temperature=0.2,
            max_tokens=900,
            response_format={"type": "json_object"},
            extra_body=NO_THINK_EXTRA_BODY,
        )
        choice = reply.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            raise BadReply(f"empty reply (finish_reason={choice.finish_reason!r}); the model produced no content")
        return content


def _reject_constant(name: str) -> None:
    raise BadReply(f"{name} is not a valid JSON number")


def parse_json_object(text: str) -> dict:
    """Strict parse: one JSON object, code fences tolerated, nothing else."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    if not cleaned:
        raise BadReply("empty reply")
    try:
        data = json.loads(cleaned, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise BadReply(f"not valid JSON ({exc.msg} at char {exc.pos})") from exc
    if not isinstance(data, dict):
        raise BadReply("reply must be a JSON object")
    return data


def _check_model_reply(data: dict, offers: list[OfferLike]) -> None:
    """Every field Super must get right before its reply is used. Each problem is a BadReply the retry prompt quotes."""
    ids = [o.call_id for o in offers]
    winner = data.get("winner_call_id")
    if winner not in ids:
        raise BadReply(f"winner_call_id {winner!r} is not one of the offers {ids}")
    ranked = data.get("ranked")
    if not isinstance(ranked, list) or not ranked:
        raise BadReply("ranked must be a non-empty list")
    for i, entry in enumerate(ranked):
        if not isinstance(entry, dict):
            raise BadReply(f"ranked[{i}] must be an object with call_id and score, got {entry!r}")
        if not isinstance(entry.get("call_id"), str):
            raise BadReply(f"ranked[{i}].call_id must be a string")
        score = entry.get("score")
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise BadReply(f"score for {entry['call_id']!r} must be a finite number from 0 to 100")
        if isinstance(score, float) and not math.isfinite(score):
            raise BadReply(f"score for {entry['call_id']!r} must be a finite number from 0 to 100")
        # Native comparison first: a huge JSON integer would raise OverflowError on float() and skip the retry.
        if not 0 <= score <= 100:
            shown = str(score) if len(str(score)) <= 20 else f"{str(score)[:12]}... ({len(str(score))} digits)"
            raise BadReply(f"score for {entry['call_id']!r} is {shown}; it must be from 0 to 100")
    ranked_ids = [entry["call_id"] for entry in ranked]
    if sorted(ranked_ids) != sorted(ids):
        raise BadReply(f"ranked must cover every offer exactly once; got {ranked_ids}, expected {ids}")
    if ranked_ids[0] != winner:
        raise BadReply("ranked[0] must be the winner")
    tradeoff = data.get("tradeoff")
    if not isinstance(tradeoff, str) or not tradeoff.strip():
        raise BadReply("tradeoff must be a non-empty sentence")


def reason_tags(winner: OfferLike, all_offers: list[OfferLike], carrier: str | None) -> tuple[list[str], list[str]]:
    """Reason chips and secondary chips in the prototype's style, computed from facts only."""
    others = [o for o in all_offers if o.call_id != winner.call_id]
    reasons = [f"Fits your free time · {slot_label(winner.slot_start)}"]
    other_prices = sorted(o.price for o in others)
    if others and winner.price <= other_prices[0]:
        reasons.append(f"Cheapest · {money(winner.price)} vs {', '.join(money(p) for p in other_prices)}")
    else:
        reasons.append(f"Price · {money(winner.price)}")
    if carrier and winner.insured:
        reasons.append(f"Takes {carrier}")

    by_distance = sorted(all_offers, key=lambda o: o.distance_mi)
    place = next(i for i, o in enumerate(by_distance) if o.call_id == winner.call_id)
    ordinal = {0: "Closest", 1: "2nd closest", 2: "3rd closest"}.get(place, f"{place + 1}th closest")
    second = [f"{ordinal} · {winner.distance_mi:g} mi"]
    return reasons, second


def rank(
    offers: list[OfferLike],
    windows: list[WindowLike],
    priority: str,
    *,
    client: ChatJSON,
    all_offers: list[OfferLike] | None = None,
    carrier: str | None = None,
) -> dict:
    """Return a Decision dict that validates against shared/decision.schema.json.

    `offers` are the hard-rule survivors; `all_offers` (default: offers) are every clinic called, so the
    price comparison in the chips covers the clinics that were ruled out too.
    """
    if not offers:
        raise ValueError("rank() needs at least one eligible offer; use ranking.no_eligible_offer instead")
    all_offers = all_offers or offers
    system, user = RANKING_SYSTEM, ranking_user_message(offers, windows, priority)
    previous: list[dict] = []
    problem = ""
    for attempt in range(2):
        reply = client.complete_json(system, user, previous=previous or None)
        try:
            data = parse_json_object(reply)
            _check_model_reply(data, offers)
            break
        except BadReply as exc:
            problem = str(exc)
            if attempt == 1:
                raise RankingError(f"Super gave no usable Decision after one retry: {problem}") from exc
            previous = [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            user = retry_user_message(reply, problem)

    by_id = {o.call_id: o for o in offers}
    winner = by_id[data["winner_call_id"]]
    reasons, second = reason_tags(winner, all_offers, carrier)
    ranked = [{"call_id": r["call_id"], "score": float(r["score"])} for r in data["ranked"]]
    decision = {
        "winner_call_id": winner.call_id,
        "score": ranked[0]["score"],
        "reasons": reasons,
        "second": second,
        "tradeoff": data["tradeoff"].strip(),
        "ranked": ranked,
    }
    errors = sorted(_validator.iter_errors(decision), key=lambda e: list(e.path))
    if errors:
        raise RankingError("Decision does not match shared/decision.schema.json: " + "; ".join(e.message for e in errors))
    return decision


def timed_rank(offers: list[OfferLike], *args, client: ChatJSON, **kwargs) -> tuple[dict, float]:
    """rank() plus wall-clock seconds; records the ranking-latency metric (model, latency_ms, offers)."""
    start = time.perf_counter()
    decision = rank(offers, *args, client=client, **kwargs)
    seconds = time.perf_counter() - start
    metrics.record_ranking(getattr(client, "model_id", type(client).__name__), round(seconds * 1000), len(offers))
    return decision, seconds
