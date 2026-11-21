"""Viewer-scoped projections: the task object from shared/task.schema.json and the snapshot sent first on GET /api/live."""

from __future__ import annotations

import json

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.events import Viewer, last_event_id, list_events
from app.models import Call, Task


def _load(blob: str | None) -> object | None:
    return json.loads(blob) if blob else None


CALL_RESULT_KEYS = ("price", "slot", "insured", "slotOk")  # shared/task.schema.json call_result


def call_projection(call: Call, meta: str | None = None) -> dict:
    """calls.result_json also carries the structured facts for ranking (price_usd, slot_start, slot_end, source);
    the card gets the four display fields the schema allows."""
    stored = _load(call.result_json)
    result = {k: stored[k] for k in CALL_RESULT_KEYS if k in stored} if isinstance(stored, dict) else None
    return {
        "call_id": call.id,
        "clinic": call.clinic_name,
        "meta": meta or (f"{call.distance_mi:g} mi" if call.distance_mi is not None else ""),
        "status": call.status,
        "result": result,
    }


def project_task(task: Task, calls: list[Call], events: list[dict], viewer: Viewer) -> dict:
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
    """The first SSE message: the viewer's current task, its calls and the events they may see. `cursor` is the owner's highest event id, the stream's starting point; it is popped before sending."""
    with Session(engine) as session:
        # The cursor is read first and every later read is bounded by it, so an event committed while the snapshot is
        # being built is left for the stream's first catch-up batch and is never both in the snapshot and re-sent.
        cursor = last_event_id(session, viewer.owner_id)
        task = latest_task(session, viewer.owner_id)
        if task is None:
            return {"type": "snapshot", "task": None, "calls": [], "events": [], "cursor": cursor}
        events = list_events(session, task.id, viewer, up_to=cursor)
        calls = session.exec(select(Call).where(Call.task_id == task.id).order_by(Call.started_at, Call.id)).all()
        return {
            "type": "snapshot",
            "task": project_task(task, list(calls), events, viewer),
            "calls": [call_projection(c) for c in calls],
            "events": events,
            "cursor": cursor,
        }
