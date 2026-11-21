"""Hard rules in code: drop offers over budget, outside free windows, or not insured. Then hand survivors to nemotron.ranker.

The rules are deterministic and run before any model sees the offers (docs/ARCHITECTURE.md, pipeline
step 5). Inputs are typed structurally against the documented Offer and Window shapes so the adapters'
Pydantic models in integrations/types.py satisfy them without an import in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

NO_ELIGIBLE_OFFER = "NO_ELIGIBLE_OFFER"

RejectReason = Literal["OVER_BUDGET", "OUTSIDE_WINDOWS", "NOT_INSURED"]


class OfferLike(Protocol):
    call_id: str
    clinic: str
    price: float
    slot_start: datetime
    slot_end: datetime
    insured: bool
    distance_mi: float
    drive_min: float


class WindowLike(Protocol):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Rejection:
    call_id: str
    clinic: str
    reasons: tuple[RejectReason, ...]
    detail: str  # one honest sentence a person can read


@dataclass(frozen=True)
class HardRuleResult:
    eligible: list
    rejected: list[Rejection]

    @property
    def ok(self) -> bool:
        return bool(self.eligible)

    def reasons_for(self, call_id: str) -> tuple[RejectReason, ...]:
        return next((r.reasons for r in self.rejected if r.call_id == call_id), ())


def fits_windows(offer: OfferLike, windows: list[WindowLike]) -> bool:
    """True when the whole slot lies inside one free window. No windows means nothing fits."""
    return any(w.start <= offer.slot_start and offer.slot_end <= w.end for w in windows)


def money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def slot_label(when: datetime) -> str:
    """Thu 9:30 — the style the prototype uses on cards and chips."""
    return f"{when:%a} {when.hour % 12 or 12}:{when:%M}"


def hard_rules(
    offers: list[OfferLike],
    windows: list[WindowLike],
    budget_max: float | None,
    carrier: str | None,
) -> HardRuleResult:
    """Split offers into eligible and rejected. A None budget or carrier means that rule does not apply."""
    eligible: list[OfferLike] = []
    rejected: list[Rejection] = []
    for offer in offers:
        reasons: list[RejectReason] = []
        details: list[str] = []
        if budget_max is not None and offer.price > budget_max:
            reasons.append("OVER_BUDGET")
            details.append(f"{money(offer.price)} is over the {money(budget_max)} budget")
        if not fits_windows(offer, windows):
            reasons.append("OUTSIDE_WINDOWS")
            details.append(f"{slot_label(offer.slot_start)} is outside the free windows")
        if carrier is not None and not offer.insured:
            reasons.append("NOT_INSURED")
            details.append(f"does not take {carrier}")
        if reasons:
            rejected.append(Rejection(offer.call_id, offer.clinic, tuple(reasons), "; ".join(details)))
        else:
            eligible.append(offer)
    return HardRuleResult(eligible=eligible, rejected=rejected)


def no_eligible_offer(result: HardRuleResult) -> dict:
    """The failure payload when nothing survives: error code plus one honest message for owner and contact."""
    if result.ok:
        raise ValueError("no_eligible_offer called with eligible offers")
    if not result.rejected:
        message = "No clinic could be reached, so nothing was booked."
    else:
        parts = [f"{r.clinic}: {r.detail}" for r in result.rejected]
        message = (
            f"None of the {len(result.rejected)} clinics fit the request, so nothing was booked. "
            + ". ".join(parts)
            + "."
        )
    return {"code": NO_ELIGIBLE_OFFER, "message": message, "rejected": [r.call_id for r in result.rejected]}
