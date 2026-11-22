"""GET /api/users/{owner_id}. The owner's on-device record for the Profile tab. Owner viewer only; never the contact."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from app.events import resolve_viewer
from app.people import load_owner
from app.session import require_session

router = APIRouter(prefix="/api/users", tags=["users"])

# What the intake step keeps and may say to a clinic (IntakeRequest); everything else in the record stays on the device.
SHARED_FIELDS = ("care_type", "budget_max", "insurance_carrier", "time_range", "needs_ride", "search_area")


def _mask_member_id(member_id: str | None) -> str | None:
    if not member_id:
        return None
    tail = member_id[-4:]
    return f"•••• {tail}"


@router.get("/{owner_id}", dependencies=[Depends(require_session)])
def get_user(owner_id: str, request: Request, viewer_id: str = Query(min_length=1)) -> dict:
    """The owner record from backend/fixtures/users.json, read-only, for the owner's own viewer. A contact viewer, or a
    viewer asking for another owner, gets 404 so the response never carries the date of birth, address or member ID
    outside the owner's scope (product rule 4, D6)."""
    with Session(request.app.state.engine) as session:
        viewer = resolve_viewer(session, viewer_id)
    if viewer.role != "owner" or viewer.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="user not found")
    try:
        user = load_owner(owner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    insurance = user.insurance
    return {
        "id": user.id,
        "name": user.name,
        "dob": user.dob,
        "timezone": user.timezone,
        "phone_e164": user.phone_e164,
        "home_address": user.home.address if user.home else None,
        "insurance": {"carrier": insurance.carrier, "member_id_masked": _mask_member_id(insurance.member_id)} if insurance else None,
        "shared_fields": list(SHARED_FIELDS),
        "kept_on_device": True,
    }
