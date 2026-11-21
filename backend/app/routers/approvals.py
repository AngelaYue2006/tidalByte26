"""POST /api/tasks/{id}/approve. Owner only. Emits approved."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import approvals
from app.events import emit_many
from app.session import require_session

router = APIRouter(prefix="/api/tasks", tags=["approvals"])


class ApprovalBody(BaseModel):
    actor_id: str = Field(min_length=1)
    decision: Literal["approve", "reject"]
    idempotency_key: str = Field(min_length=1)


@router.post("/{task_id}/approve", dependencies=[Depends(require_session)])
async def approve(task_id: str, body: ApprovalBody, request: Request) -> dict:
    """The one user gate from the dashboard. Only the owner, only while the task is awaiting approval; a repeat is answered, not re-applied."""
    try:
        return approvals.apply_decision(
            request.app.state.engine, request.app.state.bus, request.app.state.pipeline,
            task_id, body.actor_id, body.decision, "dashboard", body.idempotency_key, emit=emit_many,
        )
    except approvals.NotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except approvals.NotOwner as exc:
        raise HTTPException(status_code=403, detail="only the owner can approve") from exc
    except approvals.WrongState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
