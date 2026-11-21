"""Viewer-scoped projections: the task object from shared/task.schema.json and the snapshot sent first on GET /api/live."""

from __future__ import annotations

import json

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.events import Viewer, list_events
from app.models import Call, Task


def _load(blob: str | None) -> object | None:
    return json.loads(blob) if blob else None


def call_projection(call: Call, meta: str | None = None) -> dict:
    result = _load(call.result_json)
    return {
        "call_id": call.id,
        "clinic": call.clinic_name,
        "meta": meta or (f"{call.distance_mi:g} mi" if call.distance_mi is not None else ""),
        "status": call.status,
        "result": result,
    }


def task_projection(task: Task, calls: list[Call], events: list[dict], viewer: Viewer) -> dict:
    """One task as the viewer may see it. `request_text` exists only in the owner variant."""
    request = next((e for e in events if e["type"] == "request"), None)
    metas = {e["call_id"]: e.get("meta") for e in events if e["type"] == "call_start"}
    failed = next((e for e in reversed(events) if e["type"] == "task_updated" and e.get("status") == "failed"), None)
    projection: dict = {
        "id": task.id,
        "owner_id": task.owner_id,
        "status": task.status,
        "viewer_role": viewer.role,
        "intake": _load(task.intake_json),
        "chips": list(request.get("chips", [])) if request else [],
        "windows": _load(task.windows_json) or [],
        "calls": [call_projection(call, metas.get(call.id)) for call in calls],
        "decision": _load(task.decision_json),
        "booking": _load(task.booking_json),
        "transport": _load(task.transport_json),
        "failure_reason": failed.get("reason") if failed else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }
    if viewer.role == "owner":
        projection["request_text"] = request.get("text") if request else None
    return projection


def latest_task(session: Session, owner_id: str) -> Task | None:
    return session.exec(select(Task).where(Task.owner_id == owner_id).order_by(Task.created_at.desc(), Task.id.desc())).first()


def snapshot(engine: Engine, viewer: Viewer) -> dict:
    """The first SSE message: the viewer's current task, its calls and the events they may see. `last_event_id` is the stream id."""
    with Session(engine) as session:
        task = latest_task(session, viewer.owner_id)
        if task is None:
            return {"type": "snapshot", "task": None, "calls": [], "events": [], "last_event_id": None}
        events = list_events(session, task.id, viewer)
        calls = session.exec(select(Call).where(Call.task_id == task.id).order_by(Call.started_at, Call.id)).all()
        return {
            "type": "snapshot",
            "task": task_projection(task, list(calls), events, viewer),
            "calls": [call_projection(c) for c in calls],
            "events": events,
            "last_event_id": events[-1]["id"] if events else None,
        }
