"""Typed adapter facts. The backend owns state, approval and event publication."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Phone = Annotated[str, Field(pattern=r"^\+[1-9]\d{7,14}$")]
Nonempty = Annotated[str, Field(min_length=1)]


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Fact):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Window end must follow start")
        return self


class IntakeRequest(Fact):
    care_type: Nonempty
    budget_max: float | None = Field(default=None, ge=0)
    insurance_carrier: str | None = None
    time_range: Window
    needs_ride: bool
    search_area: str | None
    dropped_fields: list[str] = Field(default_factory=list)


class Clinic(Fact):
    id: str | None = None
    name: Nonempty
    phone_e164: Phone
    address: Nonempty
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    place_id: Nonempty
    simulated: bool = False


class Distance(Fact):
    place_id: Nonempty
    miles: float = Field(ge=0)
    minutes: float = Field(ge=0)
    simulated: bool = False


class CallSpec(Fact):
    clinic: Clinic
    request: IntakeRequest
    windows: list[Window]
    call_id: Nonempty


class CallHandle(Fact):
    call_id: Nonempty
    external_ref: Nonempty
    simulated: bool = False


class Offer(Fact):
    call_id: Nonempty
    clinic: Nonempty
    price: float = Field(ge=0)
    slot_start: AwareDatetime
    slot_end: AwareDatetime
    insured: bool
    distance_mi: float = Field(ge=0)
    drive_min: float = Field(ge=0)


class Confirmation(Fact):
    status: Literal["confirmed", "tentative", "rejected"]
    confirmation_ref: str | None = None
    evidence: str
    simulated: bool = False


class Booking(Fact):
    clinic: str
    address: str | None = None
    slot_start: AwareDatetime
    slot_end: AwareDatetime
    price: str
    status: Literal["confirmed", "tentative", "rejected"]
    confirmation_ref: str | None = None
    calendar_event_id: str | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.slot_end <= self.slot_start:
            raise ValueError("Booking end must follow start")
        return self


class CalendarReceipt(Fact):
    event_id: Nonempty
    title: Literal["Appointment"] = "Appointment"
    visibility: Literal["private"] = "private"
    reminder_minutes: Literal[1440] = 1440
    simulated: bool = False


class MessageReceipt(Fact):
    message_id: Nonempty
    text: str = Field(repr=False)
    simulated: bool = False

    def dashboard_event(self, role: Literal["owner", "contact"]) -> dict:
        """Payload for the orchestrator to publish with the correct task scope."""
        field = "sms_user" if role == "owner" else "sms_contact"
        event = {"type": "notified", "simulated": self.simulated, field: self.text}
        # The notified schema requires sms_contact; the orchestrator composes final texts.
        if role == "owner":
            event["sms_contact"] = ""
        return event


class InboundSms(Fact):
    message_id: Nonempty
    from_e164: Phone = Field(repr=False)
    body: str = Field(repr=False)
    role: Literal["owner", "contact"]
    correlation: str | None = None
    simulated: bool = False


class TransportOptions(Fact):
    available: bool
    reason: str
    simulated: bool = False

    def dashboard_event(self) -> dict:
        return {
            "type": "transport_check",
            "status": "available" if self.available else "unavailable",
            "reason": self.reason,
            "simulated": self.simulated,
        }
