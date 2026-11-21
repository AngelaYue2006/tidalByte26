"""POST /api/requests -> starts the orchestrator; returns task_id."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import session_scope
from app.models import Task
from app.people import load_owner
from app.session import require_session

router = APIRouter(prefix="/api", tags=["requests"])


class RequestBody(BaseModel):
    owner_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    text: str | None = None
    audio_b64: str | None = None
    idempotency_key: str = Field(min_length=1)


@router.post("/requests", status_code=201, dependencies=[Depends(require_session)])
async def create_request(body: RequestBody, request: Request, response: Response) -> dict:
    """Create the task and start the pipeline. The same idempotency key returns the same task without a second run."""
    pipeline = request.app.state.pipeline
    existing = pipeline.task_for_request_key(body.idempotency_key)
    if existing is not None:
        response.status_code = 200
        return {"task_id": existing}
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=422, detail="text is required; audio_b64 is not supported yet (speech-to-text happens in the browser)")
    try:
        load_owner(body.owner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    with session_scope(request.app.state.engine) as session:
        task = Task(owner_id=body.owner_id, status="intake")
        session.add(task)
        session.flush()
        task_id = task.id
    pipeline.remember_request_key(body.idempotency_key, task_id)
    pipeline.start(task_id, body.text.strip())
    return {"task_id": task_id}


def task_for_actor(session: Session, task_id: str, actor_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None or task.owner_id != actor_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task
