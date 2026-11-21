"""Event bus: persist to events table with visibility, fan out to SSE subscribers per viewer. Emits the event types in docs/ARCHITECTURE.md, Live events.

Visibility: `owner` reaches the owner only, `contact` reaches both roles, `internal` reaches no dashboard.
A viewer whose id is a row in `contacts` is a contact of that row's owner; any other viewer id is an owner.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db import session_scope
from app.models import Contact, Event, Task
from app.nemotron import intake_backstop

VISIBILITIES: tuple[str, ...] = ("owner", "contact", "internal")

# Every persisted event type from docs/ARCHITECTURE.md, Live events. snapshot and heartbeat are stream-only.
EVENT_TYPES: tuple[str, ...] = (
    "request",
    "call_start",
    "call_status",
    "transcript",
    "call_result",
    "decision",
    "booked",
    "notified",
    "approval_required",
    "approved",
    "transport_check",
    "contact_request",
    "contact_reply",
    "ride_confirmed",
    "task_updated",
)

_ROLE_SEES: dict[str, frozenset[str]] = {
    "owner": frozenset({"owner", "contact"}),
    "contact": frozenset({"contact"}),
}


@dataclass(frozen=True)
class Viewer:
    id: str
    role: str  # owner | contact
    owner_id: str  # whose tasks this viewer may see


def resolve_viewer(session: Session, viewer_id: str) -> Viewer:
    contact = session.exec(select(Contact).where(Contact.id == viewer_id)).first()
    if contact is not None:
        return Viewer(id=viewer_id, role="contact", owner_id=contact.owner_id)
    return Viewer(id=viewer_id, role="owner", owner_id=viewer_id)


def visible_to(role: str, visibility: str) -> bool:
    return visibility in _ROLE_SEES.get(role, frozenset())


REMOVED = "[removed]"


def screen_for_contact(text: str) -> str:
    """Clinic speech as the contact may see it: identifier-shaped values (member IDs, phone numbers, dates of birth,
    street addresses) found by the same on-device detector that redacts the intake are replaced. The agent's own lines
    carry only redacted facts already. The owner sees the line as spoken."""
    for value in sorted(intake_backstop.identifier_values(text), key=len, reverse=True):
        if value:
            text = text.replace(value, REMOVED)
    return text


def project_event(row: Event, role: str) -> dict:
    """The flat, schema-valid event for one role. The contact never gets `request.text`; the owner's request, which
    carries the text, is labelled `visibility: owner` because that is the variant they receive. A clinic transcript
    line reaches the contact screened (product rule 4; D6 keeps the call cards visible to both)."""
    payload = json.loads(row.payload_json)
    visibility = row.visibility
    if row.type == "request":
        if role == "contact":
            payload.pop("text", None)
        elif "text" in payload:
            visibility = "owner"
    if row.type == "transcript" and role == "contact" and payload.get("speaker") == "clinic":
        payload["text"] = screen_for_contact(str(payload.get("text") or ""))
    at = row.at if row.at.tzinfo is not None else row.at.replace(tzinfo=UTC)
    return {
        **payload,
        "type": row.type,
        "id": row.id,
        "task_id": row.task_id,
        "at": at.isoformat(),
        "visibility": visibility,
    }


@dataclass(eq=False)
class Subscription:
    viewer: Viewer
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class EventBus:
    """In-process fan-out. `publish` may be called from any thread; each subscriber's queue is fed on its own loop."""

    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._lock = threading.Lock()

    def subscribe(self, viewer: Viewer) -> Subscription:
        sub = Subscription(viewer=viewer, loop=asyncio.get_running_loop())
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, row: Event, owner_id: str) -> int:
        """Wake every subscriber of this owner. The queue carries only the event id; the stream reads the persisted
        events past its cursor in id order, so notifications may arrive late or out of order without harm."""
        with self._lock:
            subs = list(self._subs)
        fed = 0
        for sub in subs:
            if sub.viewer.owner_id != owner_id or not visible_to(sub.viewer.role, row.visibility):
                continue
            sub.loop.call_soon_threadsafe(sub.queue.put_nowait, row.id)
            fed += 1
        return fed


def emit(engine: Engine, bus: EventBus, task_id: str, type: str, payload: dict, visibility: str = "owner") -> Event:
    """Persist one event and fan it out. Raises on an unknown type or visibility, or a task that does not exist."""
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type!r}")
    if visibility not in VISIBILITIES:
        raise ValueError(f"unknown visibility {visibility!r}")
    if "type" in payload:
        raise ValueError("payload must not carry its own 'type'")
    with session_scope(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise LookupError(f"no task {task_id!r}")
        owner_id = task.owner_id
        row = Event(task_id=task_id, type=type, payload_json=json.dumps(payload, ensure_ascii=False), visibility=visibility)
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    bus.publish(row, owner_id)
    return row


def list_events(session: Session, task_id: str, viewer: Viewer, *, up_to: int | None = None) -> list[dict]:
    """Ordered events for one task, filtered by what the viewer's role may see. `up_to` bounds the list to ids at or
    below a cursor so a snapshot and the stream that follows it agree on what has been applied."""
    query = select(Event).where(Event.task_id == task_id).order_by(Event.id)
    if up_to is not None:
        query = query.where(Event.id <= up_to)
    rows = session.exec(query).all()
    return [project_event(row, viewer.role) for row in rows if visible_to(viewer.role, row.visibility)]


def events_after(session: Session, viewer: Viewer, cursor: int) -> list[dict]:
    """Every event of the viewer's owner with id > cursor, in id order, filtered by role. SQLite serialises writers,
    so ids commit in order and a cursor never skips one."""
    rows = session.exec(
        select(Event).join(Task, Task.id == Event.task_id).where(Task.owner_id == viewer.owner_id, Event.id > cursor).order_by(Event.id)
    ).all()
    return [project_event(row, viewer.role) for row in rows if visible_to(viewer.role, row.visibility)]


def last_event_id(session: Session, owner_id: str) -> int:
    """The stream cursor at snapshot time: the highest event id across the owner's tasks, 0 when none."""
    rows = session.exec(select(Event.id).join(Task, Task.id == Event.task_id).where(Task.owner_id == owner_id).order_by(Event.id.desc())).first()
    return int(rows) if rows is not None else 0
