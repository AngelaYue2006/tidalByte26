"""GET /api/tasks, GET /api/tasks/{id}, GET /api/tasks/{id}/events. Viewer-scoped projections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from app.events import list_events, resolve_viewer
from app.models import Call, Task
from app.projections import project_task
from app.session import require_session

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _scoped_task(session: Session, task_id: str, viewer_id: str) -> tuple[Task, object]:
    viewer = resolve_viewer(session, viewer_id)
    task = session.get(Task, task_id)
    if task is None or task.owner_id != viewer.owner_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task, viewer


def _projection(session: Session, task: Task, viewer) -> dict:
    events = list_events(session, task.id, viewer)
    calls = session.exec(select(Call).where(Call.task_id == task.id).order_by(Call.started_at, Call.id)).all()
    return project_task(task, list(calls), events, viewer)


@router.get("", dependencies=[Depends(require_session)])
def list_tasks(request: Request, viewer_id: str = Query(min_length=1), owner_id: str | None = None, limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    """History, newest first, for the viewer's owner. `owner_id` must match the viewer's scope or the list is empty."""
    with Session(request.app.state.engine) as session:
        viewer = resolve_viewer(session, viewer_id)
        if owner_id is not None and owner_id != viewer.owner_id:
            return []
        tasks = session.exec(select(Task).where(Task.owner_id == viewer.owner_id).order_by(Task.created_at.desc(), Task.id.desc()).limit(limit)).all()
        return [_projection(session, task, viewer) for task in tasks]


@router.get("/{task_id}", dependencies=[Depends(require_session)])
def get_task(task_id: str, request: Request, viewer_id: str = Query(min_length=1)) -> dict:
    """The task projection for the viewer's role (shared/task.schema.json)."""
    with Session(request.app.state.engine) as session:
        task, viewer = _scoped_task(session, task_id, viewer_id)
        return _projection(session, task, viewer)


@router.get("/{task_id}/events", dependencies=[Depends(require_session)])
def task_events(task_id: str, request: Request, viewer_id: str = Query(min_length=1)) -> list[dict]:
    """The same filtered, ordered list the SSE stream carries. 404 for a task outside the viewer's scope."""
    with Session(request.app.state.engine) as session:
        viewer = resolve_viewer(session, viewer_id)
        task = session.get(Task, task_id)
        if task is None or task.owner_id != viewer.owner_id:
            raise HTTPException(status_code=404, detail="task not found")
        return list_events(session, task_id, viewer)
