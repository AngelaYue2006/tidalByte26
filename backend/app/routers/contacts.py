"""POST /api/contacts/offers. Contact dashboard reply. Emits contact_reply, ride_confirmed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.events import emit
from app.models import Contact, Task
from app.session import require_session

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class Offer(BaseModel):
    can_drive: bool
    pickup_time: str | None = None


class OfferBody(BaseModel):
    task_id: str = Field(min_length=1)
    contact_id: str = Field(min_length=1)
    offer: Offer
    idempotency_key: str = Field(min_length=1)


@router.post("/offers", dependencies=[Depends(require_session)])
async def contact_offer(body: OfferBody, request: Request) -> dict:
    """The contact's answer from the dashboard. A ride offer confirms the ride and resumes the task; a decline is
    recorded and the task keeps waiting (T10). Only the owner's own contact, only while awaiting the contact."""
    engine, bus, pipeline = request.app.state.engine, request.app.state.bus, request.app.state.pipeline
    with Session(engine) as session:
        task = session.get(Task, body.task_id)
        contact = session.get(Contact, body.contact_id)
        if task is None or contact is None or contact.owner_id != task.owner_id:
            raise HTTPException(status_code=404, detail="task not found")
        status, name, booking_json = task.status, contact.name, task.booking_json
    if status != "awaiting_contact":
        raise HTTPException(status_code=409, detail=f"task is {status}, not awaiting the contact")
    first = name.split()[0]
    text = "I can drive." if body.offer.can_drive else "I can't drive this time."
    emit(engine, bus, body.task_id, "contact_reply", {"contact": first, "text": text, "offer": body.offer.model_dump()}, "contact")
    if not body.offer.can_drive:
        return {"status": "awaiting_contact", "ride": "declined"}
    pickup = body.offer.pickup_time or _default_pickup(booking_json)
    emit(engine, bus, body.task_id, "ride_confirmed", {"driver": first, "pickup_time": pickup}, "contact")
    pipeline.resume(body.task_id)
    return {"status": "ride_confirmed", "pickup_time": pickup}


def _default_pickup(booking_json: str | None) -> str:
    """Thirty minutes before the appointment when the contact names no time."""
    import json
    from datetime import datetime, timedelta

    if not booking_json:
        return ""
    start = datetime.fromisoformat(json.loads(booking_json)["slot_start"])
    return (start - timedelta(minutes=30)).isoformat()
