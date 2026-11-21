"""Receipts: every external side effect and every idempotent reply happens once per (task, step).

`once()` returns the stored payload when a receipt exists and otherwise runs `produce`, stores its result and the
adapter id, and returns it. The unique index on (task_id, step) makes two concurrent attempts race on the INSERT:
the loser rolls back, re-reads the winner's row and returns that, so the adapter is called once (invariant 7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import session_scope
from app.models import Receipt


def find(engine: Engine, task_id: str, step: str) -> Receipt | None:
    with Session(engine) as session:
        return session.exec(select(Receipt).where(Receipt.task_id == task_id, Receipt.step == step)).first()


def payload_of(receipt: Receipt) -> dict:
    return json.loads(receipt.payload_json or "{}")


def record(engine: Engine, task_id: str, step: str, kind: str, payload: dict, external_id: str | None = None) -> tuple[dict, bool]:
    """Store a receipt. Returns (payload, repeated): the stored payload, and whether a receipt already existed."""
    row = Receipt(task_id=task_id, step=step, kind=kind, external_id=external_id, payload_json=json.dumps(payload, ensure_ascii=False, default=str))
    try:
        with session_scope(engine) as session:
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = find(engine, task_id, step)
        return (payload_of(existing) if existing else payload), True
    return payload, False


def once(
    engine: Engine,
    task_id: str,
    step: str,
    kind: str,
    produce: Callable[[], Any],
    *,
    external_id: Callable[[Any], str | None] = lambda result: None,
    to_payload: Callable[[Any], dict] = lambda result: result if isinstance(result, dict) else result.model_dump(mode="json"),
) -> tuple[dict, bool]:
    """Run `produce` unless a receipt for (task_id, step) exists. Returns (payload, repeated).

    The receipt is written right after the effect succeeds. If the effect raises, nothing is written and a retry
    runs it again, which is what every adapter in this project promises is safe (their own idempotency keys).
    """
    existing = find(engine, task_id, step)
    if existing is not None:
        return payload_of(existing), True
    result = produce()
    payload = to_payload(result)
    stored, repeated = record(engine, task_id, step, kind, payload, external_id(result))
    return stored, repeated


def find_by_step(engine: Engine, step: str) -> Receipt | None:
    """A receipt looked up by its step alone, for keys that arrive before the task is known (request keys)."""
    with Session(engine) as session:
        return session.exec(select(Receipt).where(Receipt.step == step)).first()
