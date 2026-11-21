"""POST /api/contacts/offers. Contact dashboard reply. Emits contact_reply, ride_confirmed (app/contact_replies.py decides)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app import contact_replies
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
    recorded, the owner is told and the task keeps waiting (T10). Only the owner's own contact, only while awaiting the contact."""
    engine, bus, pipeline = (
        request.app.state.engine,
        request.app.state.bus,
        request.app.state.pipeline,
    )
    with Session(engine) as session:
        task = session.get(Task, body.task_id)
        contact = session.get(Contact, body.contact_id)
        if task is None or contact is None or contact.owner_id != task.owner_id:
            raise HTTPException(status_code=404, detail="task not found")
        status, name = task.status, contact.name
    replayed = pipeline.replay("contact_offer", body.task_id, body.idempotency_key)
    if replayed is not None:
        return replayed  # the same key again: the same answer, no second reply or confirmation
    if status != "awaiting_contact" or not pipeline.waiting(body.task_id):
        raise HTTPException(
            status_code=409, detail=f"task is {status}, not awaiting the contact"
        )
    first = name.split()[0]
    if not body.offer.can_drive:
        result = contact_replies.decline(
            engine, bus, pipeline, body.task_id, first, "I can't drive this time."
        )
        return pipeline.remember(
            "contact_offer", body.task_id, body.idempotency_key, result
        )
    result = contact_replies.confirm_ride(
        engine,
        bus,
        pipeline,
        body.task_id,
        first,
        "I can drive.",
        body.offer.pickup_time,
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="a ride for this task was already confirmed"
        )
    return pipeline.remember(
        "contact_offer", body.task_id, body.idempotency_key, result
    )
