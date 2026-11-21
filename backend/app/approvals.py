"""The one user gate, applied the same way from the dashboard POST and from an SMS reply.

`apply_decision` checks the actor, claims the task's wait, writes the approval (or the cancellation) and the
`approved` event in one transaction, resumes the pipeline, and answers idempotently by key. Nothing here books;
the orchestrator only moves past `awaiting_approval` once the `approved` event exists (product rule 2).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import Engine
from sqlmodel import Session

from app.events import EventBus, emit_many
from app.models import Task
from app.state import transition

Decision = Literal["approve", "reject"]
Via = Literal["dashboard", "sms"]

APPROVE_WORDS = frozenset({"yes", "y", "yes.", "approve", "ok", "okay", "book", "book it"})
REJECT_WORDS = frozenset({"no", "n", "no.", "reject", "cancel", "stop", "don't", "dont"})

# Once approval has been applied, a later approve is answered, never re-applied.
ALREADY_APPROVED = ("awaiting_approval", "booking", "transport", "awaiting_contact", "completed")


class NotFound(LookupError):
    pass


class NotOwner(PermissionError):
    pass


class WrongState(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"task is {status}, not awaiting approval")
        self.status = status


def decision_from_text(body: str) -> Decision | None:
    """YES/Y (and a few plain synonyms) approve, NO/N/reject/cancel reject, anything else is not an answer."""
    word = " ".join(body.strip().lower().split())
    if word in APPROVE_WORDS:
        return "approve"
    if word in REJECT_WORDS:
        return "reject"
    return None


def apply_decision(
    engine: Engine, bus: EventBus, pipeline, task_id: str, actor_id: str, decision: Decision, via: Via, key: str, *, emit=emit_many
) -> dict:
    """Apply the owner's answer once. Returns the reply dict the route or webhook sends back.

    Raises NotFound, NotOwner or WrongState for the caller to turn into its own status codes. `emit` is the
    transactional event writer (events.emit_many); callers pass their own reference so tests can make it fail.
    """
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise NotFound(task_id)
        if task.owner_id != actor_id:
            raise NotOwner(actor_id)
        status = task.status
    replayed = pipeline.replay(via, task_id, key)
    if replayed is not None:
        return replayed  # the same key again: the same answer, nothing re-applied
    if status != "awaiting_approval" or not pipeline.claim_wait(task_id):
        if status in ALREADY_APPROVED and decision == "approve":
            return {"status": status, "applied": False}  # already approved (or being applied): idempotent
        raise WrongState(status)
    # The reply's writes are one transaction; if they fail the claim is released so a retry can resume the wait.
    try:
        if decision == "approve":
            emit(engine, bus, task_id, [("approved", {"by": actor_id, "via": via}, "contact")])
        else:
            emit(
                engine, bus, task_id,
                [("task_updated", {"status": "cancelled", "reason": "REJECTED_BY_OWNER"}, "contact")],
                before=lambda _session, task: transition(task, "cancelled"),
            )
    except Exception:
        pipeline.release_wait(task_id)
        raise
    pipeline.resume(task_id)
    return pipeline.remember(via, task_id, key, {"status": "approved" if decision == "approve" else "cancelled", "applied": True})
