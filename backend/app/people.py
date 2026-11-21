"""The owner's on-device record and the contacts, from backend/fixtures/users.json; demo reset (app/seed.py) reseeds the contacts table from the same file."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from app.models import Contact
from app.nemotron.types import UserRecord

USERS_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "users.json"


def _users() -> dict:
    return json.loads(USERS_FIXTURE.read_text(encoding="utf-8"))


def load_owner(owner_id: str) -> UserRecord:
    owner = _users()["owner"]
    if owner["id"] != owner_id:
        raise LookupError(f"no owner {owner_id!r} in the fixture")
    return UserRecord.model_validate(owner)


def ensure_contacts(session: Session, owner_id: str) -> list[Contact]:
    """The owner's contacts from the contacts table, seeded from the fixture on first use so the contact viewer resolves."""
    rows = session.exec(select(Contact).where(Contact.owner_id == owner_id)).all()
    if rows:
        return list(rows)
    seeded = []
    for c in _users()["contacts"]:
        if c["owner_id"] != owner_id:
            continue
        row = Contact(id=c["id"], owner_id=owner_id, name=c["name"], phone_e164=c["phone_e164"], relationship=c["relationship"], scope=c.get("scope", "ride_requests"))
        session.add(row)
        seeded.append(row)
    session.flush()
    return seeded
