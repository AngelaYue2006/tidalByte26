"""ORM models for tasks, contacts, calls, turns, events, receipts. Mirrors docs/ARCHITECTURE.md, Data model."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    status: str = Field(default="intake", index=True)
    intake_json: str | None = None
    windows_json: str | None = None
    decision_json: str | None = None
    booking_json: str | None = None
    transport_json: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Contact(SQLModel, table=True):
    __tablename__ = "contacts"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    name: str
    phone_e164: str
    relationship: str
    scope: str = "ride_requests"


class Call(SQLModel, table=True):
    __tablename__ = "calls"

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    clinic_name: str
    clinic_phone: str
    distance_mi: float | None = None
    status: str = "dialing"
    result_json: str | None = None
    external_ref: str | None = None  # ElevenLabs conversation id
    started_at: datetime | None = None
    ended_at: datetime | None = None


class Turn(SQLModel, table=True):
    __tablename__ = "turns"

    id: str = Field(default_factory=new_id, primary_key=True)
    call_id: str = Field(foreign_key="calls.id", index=True)
    seq: int
    speaker: str  # agent | clinic
    text: str  # text only, never audio
    at: datetime = Field(default_factory=now)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    type: str
    payload_json: str
    visibility: str = "owner"  # owner | contact | internal
    at: datetime = Field(default_factory=now)


class Receipt(SQLModel, table=True):
    """One external side effect or one idempotent reply, keyed by task and step (docs/ARCHITECTURE.md, Data model).

    `step` is unique per task ("sms:approval", "calendar", "booking:confirm", "reply:approve:<key>", "request:<key>");
    the row is written in the same moment the effect happens, so a retry finds it and does nothing twice.
    """

    __tablename__ = "receipts"
    __table_args__ = (Index("uq_receipts_task_step", "task_id", "step", unique=True),)

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    step: str = Field(index=True)
    kind: str  # sms | calendar | booking | reply | request
    external_id: str | None = None  # the adapter's id: message id, calendar event id, confirmation ref
    payload_json: str = "{}"  # what the effect returned, replayed to a retry
    at: datetime = Field(default_factory=now)


TABLES: tuple[str, ...] = ("tasks", "contacts", "calls", "turns", "events", "receipts")
