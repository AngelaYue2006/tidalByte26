"""Ranking rubric for Nemotron Super: the system prompt and the facts-only user message.

Lives here rather than in prompts.py while #10 holds that file; move it there once #10 merges.
Only hard-rule survivors reach this prompt, and only their Offer fields: no utterance, no identifiers.
"""

from __future__ import annotations

import json

from app.ranking import OfferLike, WindowLike, money, slot_label

RANKING_SYSTEM = """You rank dental and medical appointment offers for an older adult's assistant.
Every offer you see already passed the hard rules: it is within budget, inside a free window and covered by the insurance.
Your job is to pick the best one, score each, and explain the trade-off in one plain sentence.

Rubric, most important first:
1. Fit with the person's priority (given as "priority").
2. Lower price.
3. Sooner appointment.
4. Shorter drive.
Never invent facts. Use only the numbers given. Never mention the patient by name.

Return ONLY a JSON object with exactly these keys:
{
  "winner_call_id": "<call_id of the best offer>",
  "ranked": [{"call_id": "<id>", "score": <0-100 number>}, ...],   // every offer, best first
  "tradeoff": "<one sentence: what the runner-up did better and why it still lost>"
}
Scores are 0 to 100, higher is better. Write the trade-off in the second person, like "Smile Co. is closer (0.6 mi), but its only opening is Friday at 4, when your calendar is busy."
"""


def offer_facts(offer: OfferLike) -> dict:
    return {
        "call_id": offer.call_id,
        "clinic": offer.clinic,
        "price": money(offer.price),
        "slot": slot_label(offer.slot_start),
        "slot_start": offer.slot_start.isoformat(),
        "distance_mi": offer.distance_mi,
        "drive_min": offer.drive_min,
    }


def ranking_user_message(offers: list[OfferLike], windows: list[WindowLike], priority: str) -> str:
    payload = {
        "priority": priority,
        "free_windows": [{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in windows],
        "offers": [offer_facts(o) for o in offers],
    }
    return json.dumps(payload, ensure_ascii=False)


def retry_user_message(previous_reply: str, problem: str) -> str:
    return (
        "Your previous reply was rejected: "
        + problem
        + "\nReply again with ONLY the JSON object described, no prose, no code fences.\nPrevious reply:\n"
        + previous_reply
    )
