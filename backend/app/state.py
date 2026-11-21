"""Task status transitions: intake -> calendar -> places -> calling -> ranking -> awaiting_approval -> booking -> transport -> awaiting_contact -> completed | failed | cancelled.

The orchestrator moves a task only through `transition`, so an illegal move is a bug that raises here
instead of a status that lies on the dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

STATUSES: tuple[str, ...] = (
    "intake",
    "calendar",
    "places",
    "calling",
    "ranking",
    "awaiting_approval",
    "booking",
    "transport",
    "awaiting_contact",
    "completed",
    "failed",
    "cancelled",
)

TERMINAL: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# The happy path, in order. Every non-terminal status may also go to failed or cancelled.
_NEXT: dict[str, str] = {
    "intake": "calendar",
    "calendar": "places",
    "places": "calling",
    "calling": "ranking",
    "ranking": "awaiting_approval",
    "awaiting_approval": "booking",
    "booking": "transport",
    "transport": "awaiting_contact",
    "awaiting_contact": "completed",
}

TRANSITIONS: dict[str, frozenset[str]] = {
    status: frozenset({_NEXT[status], "failed", "cancelled"}) for status in _NEXT
} | {status: frozenset() for status in TERMINAL}
# A ride that is available skips the contact step (pipeline step 8).
TRANSITIONS["transport"] = TRANSITIONS["transport"] | {"completed"}


class IllegalTransition(Exception):
    """Raised when a task is asked to move to a status it cannot reach from where it is."""


class HasStatus(Protocol):
    status: str
    updated_at: datetime


def can_transition(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())


def transition(task: HasStatus, to: str) -> HasStatus:
    """Move `task` to status `to` in place, or raise IllegalTransition. Does not persist."""
    if to not in STATUSES:
        raise IllegalTransition(f"unknown status {to!r}; known: {', '.join(STATUSES)}")
    if task.status not in STATUSES:
        raise IllegalTransition(f"task {getattr(task, 'id', '?')} has unknown status {task.status!r}")
    if not can_transition(task.status, to):
        raise IllegalTransition(f"task {getattr(task, 'id', '?')} cannot move from {task.status!r} to {to!r}")
    task.status = to
    task.updated_at = datetime.now(UTC)
    return task
