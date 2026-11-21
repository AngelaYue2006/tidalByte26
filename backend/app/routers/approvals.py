"""POST /api/tasks/{id}/approve. Owner only. Emits approved."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import session_scope
from app.events import emit
from app.models import Task
from app.session import require_session
from app.state import transition

router = APIRouter(prefix="/api/tasks", tags=["approvals"])


class ApprovalBody(BaseModel):
    actor_id: str = Field(min_length=1)
    decision: Literal["approve", "reject"]
    idempotency_key: str = Field(min_length=1)


@router.post("/{task_id}/approve", dependencies=[Depends(require_session)])
async def approve(task_id: str, body: ApprovalBody, request: Request) -> dict:
    """The one user gate. Only the owner, only while the task is awaiting approval; a repeat is answered, not re-applied."""
    engine, bus, pipeline = request.app.state.engine, request.app.state.bus, request.app.state.pipeline
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        if task.owner_id != body.actor_id:
            raise HTTPException(status_code=403, detail="only the owner can approve")
        status = task.status
    replayed = pipeline.replay("approve", task_id, body.idempotency_key)
    if replayed is not None:
        return replayed  # the same key again: the same answer, nothing re-applied
    if status != "awaiting_approval" or not pipeline.claim_wait(task_id):
        if status in ("awaiting_approval", "booking", "transport", "awaiting_contact", "completed") and body.decision == "approve":
            return {"status": status, "applied": False}  # already approved (or being applied): idempotent
        raise HTTPException(status_code=409, detail=f"task is {status}, not awaiting approval")
    if body.decision == "approve":
        emit(engine, bus, task_id, "approved", {"by": body.actor_id, "via": "dashboard"}, "contact")
    else:
        with session_scope(engine) as session:
            transition(session.get(Task, task_id), "cancelled")
        emit(engine, bus, task_id, "task_updated", {"status": "cancelled", "reason": "REJECTED_BY_OWNER"}, "contact")
    pipeline.resume(task_id)
    return pipeline.remember("approve", task_id, body.idempotency_key, {"status": "approved" if body.decision == "approve" else "cancelled", "applied": True})
