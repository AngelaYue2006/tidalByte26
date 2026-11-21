"""Nemotron input and output types: UserRecord (on-device only), IntakeRequest and TimeRange (mirror shared/intake_request.schema.json), CallSpec (one clinic call, redacted)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Names the device may report in dropped_fields. Field names only, never values.
DROPPABLE_FIELDS: tuple[str, ...] = (
    "symptoms",
    "medications",
    "member_id",
    "date_of_birth",
    "address",
    "contact_phone",
    "patient_name",
    "mobility_details",
)


class TimeRange(BaseModel):
    """Date range the request may be scheduled in, ISO date-times in the owner's timezone."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str


class IntakeRequest(BaseModel):
    """The redacted request. The only thing allowed to leave the device."""

    model_config = ConfigDict(extra="forbid")

    care_type: str = Field(min_length=1)
    budget_max: int | float | None = Field(default=None, ge=0)
    insurance_carrier: str | None = None
    time_range: TimeRange
    needs_ride: bool
    search_area: str | None = None
    dropped_fields: list[str] = Field(default_factory=list)


class HomeLocation(BaseModel):
    address: str
    lat: float
    lng: float


class Insurance(BaseModel):
    carrier: str
    member_id: str | None = None


class UserRecord(BaseModel):
    """The owner's full record as stored on the device (backend/fixtures/users.json, `owner`). Never sent anywhere."""

    id: str
    name: str
    phone_e164: str
    timezone: str = "America/Chicago"
    dob: str | None = None
    home: HomeLocation | None = None
    insurance: Insurance | None = None


class CallSpec(BaseModel):
    """What the call agent may know on one call (routers/llm_proxy.py builds it from the calls and tasks rows). Everything here is already redacted."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    task_id: str
    clinic_name: str
    care_type: str
    budget_max: int | float | None = None
    insurance_carrier: str | None = None
    windows: list[tuple[datetime, datetime]] = Field(default_factory=list)
