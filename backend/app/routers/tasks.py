"""GET /api/tasks, GET /api/tasks/{id}, GET /api/tasks/{id}/events. Viewer-scoped projections.

Only the events route is here so far (issue #9); the list and single-task routes land with the orchestrator (#11).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from app.events import list_events, resolve_viewer
from app.models import Task
from app.session import require_session

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}/events", dependencies=[Depends(require_session)])
def task_events(task_id: str, request: Request, viewer_id: str = Query(min_length=1)) -> list[dict]:
    """The same filtered, ordered list the SSE stream carries. 404 for a task outside the viewer's scope."""
    with Session(request.app.state.engine) as session:
        viewer = resolve_viewer(session, viewer_id)
        task = session.get(Task, task_id)
        if task is None or task.owner_id != viewer.owner_id:
            raise HTTPException(status_code=404, detail="task not found")
        return list_events(session, task_id, viewer)
