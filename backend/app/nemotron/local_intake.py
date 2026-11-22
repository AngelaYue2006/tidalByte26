"""Nemotron Nano, 4-bit, local via Ollama. redact(utterance, user) -> IntakeRequest; contact_message(owner, intake, facts, ...) -> ContactMessage. The raw utterance must never leave this module for a network call."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from app import metrics
from app.nemotron import intake_backstop as backstop
from app.nemotron.prompts import (
    CONTACT_MESSAGE_SCHEMA,
    INTAKE_OUTPUT_SCHEMA,
    contact_system_prompt,
    intake_system_prompt,
)
from app.nemotron.types import DROPPABLE_FIELDS, IntakeRequest, TimeRange, UserRecord

log = logging.getLogger(__name__)

INTAKE_INCOMPLETE = "INTAKE_INCOMPLETE"
# Measured on the demo laptop (#52): 2.1 s warm with thinking off, 9.5 s with it on, 10.4 s while the model loads.
# Every request turns thinking off and asks Ollama to keep the model resident for the whole demo.
THINK = False
KEEP_ALIVE = "30m"


class IntakeError(Exception):
    """Intake could not produce a usable request. The message never contains the utterance."""


class IntakeModel(Protocol):
    name: str

    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def assert_local_ollama_url(base_url: str) -> str:
    """The raw utterance goes to this URL. It must be this machine: loopback or a *.localhost name."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (host in _LOCAL_HOSTS or host.endswith(".localhost")):
        raise IntakeError(
            "OLLAMA_BASE_URL must point at this machine (localhost, 127.0.0.1, ::1 or *.localhost); "
            f"refusing to send intake text to {host or base_url!r}"
        )
    return base_url.rstrip("/")


class OllamaClient:
    """The only network client in this module. Talks to a local OLLAMA_BASE_URL and nowhere else, ignoring proxies."""

    def __init__(self, base_url: str, model_tag: str | None, timeout_s: float = 60.0) -> None:
        if not model_tag:
            raise IntakeError("NEMOTRON_NANO_TAG is not set; the intake model has no default")
        self.base_url = assert_local_ollama_url(base_url)
        self.name = model_tag
        self.timeout_s = timeout_s
        # trust_env=False: no HTTP(S)_PROXY from the environment can route the request off the machine.
        self._http = httpx.Client(base_url=self.base_url, trust_env=False, timeout=timeout_s)

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.name,
            "stream": False,
            "format": schema,
            "think": THINK,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = self._http.post("/api/chat", json=body)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise IntakeError(f"Ollama is not reachable at {self.base_url}; start it with `ollama run <tag>`") from exc
        except httpx.HTTPError as exc:
            raise IntakeError(f"Ollama request failed: {exc.__class__.__name__}") from exc
        content = response.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise IntakeError("Ollama returned something that is not JSON") from exc


    def warm_up(self) -> bool:
        """Load the model now so the first real intake is not the 10 s one. An empty generate makes Ollama load the
        model and keep it for KEEP_ALIVE. Never raises: no Ollama means no warm-up, not a failed startup."""
        try:
            response = self._http.post("/api/generate", json={"model": self.name, "think": THINK, "keep_alive": KEEP_ALIVE})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("intake warm-up skipped: Ollama at %s said %s", self.base_url, exc.__class__.__name__)
            return False
        log.info("intake model %s loaded and kept for %s", self.name, KEEP_ALIVE)
        return True


def from_env() -> OllamaClient:
    """Read OLLAMA_BASE_URL and NEMOTRON_NANO_TAG. No model tag is invented."""
    return OllamaClient(os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"), os.environ.get("NEMOTRON_NANO_TAG"))


def warm_up_in_background(base_url: str, model_tag: str | None, timeout_s: float = 120.0) -> threading.Thread | None:
    """Start the warm-up on a daemon thread at app startup. Returns the thread, or None when there is no tag to load.
    Startup never waits on it and never fails because of it."""
    if not model_tag:
        log.info("intake warm-up skipped: NEMOTRON_NANO_TAG is not set")
        return None
    try:
        client = OllamaClient(base_url, model_tag, timeout_s=timeout_s)
    except IntakeError as exc:
        log.warning("intake warm-up skipped: %s", exc)
        return None
    thread = threading.Thread(target=client.warm_up, name="nano-warm-up", daemon=True)
    thread.start()
    return thread


def redact(utterance: str, user: UserRecord, *, model: IntakeModel | None = None, now: datetime | None = None) -> IntakeRequest:
    """Turn the raw utterance into the redacted IntakeRequest on the device.

    The model proposes; deterministic code decides budget, carrier, ride need, time range and the
    identifier kinds that were dropped, then checks that no dropped value survived.
    """
    if not utterance or not utterance.strip():
        raise IntakeError(f"{INTAKE_INCOMPLETE}: empty request")
    model = model or from_env()
    tz = ZoneInfo(user.timezone)
    now = now.astimezone(tz) if now else datetime.now(tz)
    log.debug("intake raw utterance (%d chars): %s", len(utterance), utterance)

    started = time.perf_counter()
    proposal = model.complete_json(intake_system_prompt(timezone=user.timezone), utterance, INTAKE_OUTPUT_SCHEMA)
    model_ms = round((time.perf_counter() - started) * 1000)
    if not isinstance(proposal, dict):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: model returned no object")

    request = _merge(utterance, proposal, now)
    request = _validate_outgoing(utterance, user, request)
    total_ms = round((time.perf_counter() - started) * 1000)
    metrics.record(
        "intake",
        model=model.name,
        model_ms=model_ms,
        latency_ms=total_ms,
        utterance_chars=len(utterance),
        cloud_bytes=len(request.model_dump_json().encode("utf-8")),  # all that leaves the device
        kept=[k for k, v in request.model_dump().items() if k != "dropped_fields" and v not in (None, "", [])],
        dropped=request.dropped_fields,
    )
    log.info("intake done in %d ms: kept %d fields, dropped %s", total_ms, len(request.model_dump()) - 1, request.dropped_fields)
    return request


def _merge(utterance: str, proposal: dict, now: datetime) -> IntakeRequest:
    care_type = backstop.normalise_care_type(str(proposal.get("care_type") or ""))
    if not care_type:
        raise IntakeError(f"{INTAKE_INCOMPLETE}: no care type found")

    budget = backstop.extract_budget(utterance)
    if budget is None:
        proposed = proposal.get("budget_max")
        budget = int(proposed) if isinstance(proposed, (int, float)) and not isinstance(proposed, bool) and proposed > 0 else None

    carrier = backstop.extract_carrier(utterance)
    if carrier is None:
        proposed_carrier = proposal.get("insurance_carrier")
        if isinstance(proposed_carrier, str) and proposed_carrier.strip() and not re.search(r"\d", proposed_carrier):
            carrier = proposed_carrier.strip()

    phrase = str(proposal.get("time_phrase") or "").strip().lower()
    if phrase not in backstop.TIME_PHRASES:
        phrase = backstop.extract_time_phrase(utterance) or "any"
    start, end = backstop.resolve_time_range(phrase, now)

    ride = backstop.extract_needs_ride(utterance)
    if ride is None:
        ride = bool(proposal.get("needs_ride", False))

    dropped: list[str] = []
    for name in proposal.get("dropped_fields") or []:
        if name in DROPPABLE_FIELDS and name not in dropped:
            dropped.append(name)
    for name in backstop.detect_identifiers(utterance):
        if name not in dropped:
            dropped.append(name)

    area = proposal.get("search_area")
    area = area.strip() if isinstance(area, str) and area.strip() else "near home"
    if re.search(r"\d", area) or backstop.detect_identifiers(area):
        area = "near home"
        if "address" not in dropped:
            dropped.append("address")

    dropped.sort(key=DROPPABLE_FIELDS.index)
    return IntakeRequest(
        care_type=care_type,
        budget_max=budget,
        insurance_carrier=carrier,
        time_range=TimeRange(start=start, end=end),
        needs_ride=ride,
        search_area=area,
        dropped_fields=dropped,
    )


def _owner_values(user: UserRecord) -> list[str]:
    """The owner's own identifiers from the on-device record. None of them may appear in the request."""
    values = [part for part in re.split(r"\s+", user.name) if len(part) >= 3]
    values += [user.phone_e164, user.phone_e164.removeprefix("+1"), user.dob or ""]
    if user.insurance and user.insurance.member_id:
        values.append(user.insurance.member_id)
    if user.home:
        values.append(user.home.address.split(",")[0])
    return [v for v in values if v]


def _validate_outgoing(utterance: str, user: UserRecord, request: IntakeRequest) -> IntakeRequest:
    """Fail closed: nothing sensitive leaves the device.

    Checked against identifier strings found in the utterance, the owner's own record and the sensitive lexicon.
    care_type cannot be defaulted, so an unsafe one raises; carrier and search area fall back to their safe values.
    """
    leaks = backstop.identifier_values(utterance) + _owner_values(user)
    data = request.model_dump()

    # care_type: only appointment vocabulary may leave. A name, a symptom or an unknown procedure refuses the request.
    if backstop.unsafe_terms(data["care_type"], leaks) or re.search(r"\d", data["care_type"]):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: care type carried something that must not leave the device")
    if unknown := backstop.unsupported_care_terms(data["care_type"]):
        log.warning("intake: care type refused, %d word(s) outside the appointment vocabulary", len(unknown))
        raise IntakeError(f"{INTAKE_INCOMPLETE}: care type is not a supported appointment term")

    # insurance_carrier: only a carrier the backstop knows, in its canonical spelling, or null.
    carrier = data.get("insurance_carrier")
    if isinstance(carrier, str):
        canonical = backstop.extract_carrier(carrier)
        if canonical != carrier:
            data["insurance_carrier"] = canonical
            log.warning("intake: insurance carrier %s", "normalised" if canonical else "replaced with null")

    # search_area: "near home", or a place verified on the device (known list, and spoken in the utterance).
    # Anything else, a name shaped like a place included, becomes "near home".
    area = data.get("search_area") or "near home"
    if area != "near home":
        place = backstop.verified_place(area, utterance)
        if place is None:
            data["search_area"] = "near home"
            dropped_kind = "address" if backstop.detect_identifiers(area) or re.search(r"\d", area) else "patient_name"
            if dropped_kind not in data["dropped_fields"]:
                data["dropped_fields"].append(dropped_kind)
            log.warning("intake: search area replaced with 'near home': not a verified place")
        else:
            data["search_area"] = place

    data["dropped_fields"].sort(key=DROPPABLE_FIELDS.index)
    serialized = json.dumps(data).lower()
    if any(value.lower() in serialized for value in leaks if len(value) >= 3):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: an identifier survived redaction")
    return IntakeRequest.model_validate(data)


# ---- contact message (step 9) -------------------------------------------------------------------------------------
# Product rule 4: the contact gets clinic, time, address and the ride need, nothing else. Nano writes the message from
# the full on-device record (docs/DECISIONS.md, local model section) and deterministic code checks it. When the check
# fails, or Ollama is down, the templated message from app.texts is used, so the demo never stalls on this step.


@dataclass(frozen=True)
class ContactFacts:
    """The four things the contact may learn, plus the two first names. Everything else in the record stays behind."""

    owner_first_name: str
    contact_first_name: str
    care_type: str
    clinic: str
    slot_start: datetime
    address: str


@dataclass(frozen=True)
class ContactMessage:
    text: str
    source: str  # "nano" when the model's text passed the check, "template" otherwise
    violations: tuple[str, ...] = ()  # why the model's text was refused, as kinds, never values


def contact_message(
    owner: UserRecord, intake: IntakeRequest, facts: ContactFacts, *, relationship: str, request_text: str | None = None,
    template: str, model: IntakeModel | None = None,
) -> ContactMessage:
    """Write the scoped ride request for the contact on the device.

    `template` is the deterministic fallback (app.texts.contact_request_message). The model sees the whole record,
    including `request_text`, because Ollama is local; what it writes is checked against that record before use.
    """
    started = time.perf_counter()
    record = {
        "owner": owner.model_dump(),
        "request": intake.model_dump(mode="json"),
        "spoken_request": request_text or "",
        "appointment": {"for": facts.care_type, "clinic": facts.clinic, "when": _when(facts.slot_start), "address": facts.address, "owner_first_name": facts.owner_first_name},
        "contact": {"first_name": facts.contact_first_name, "relationship": relationship},
        "transport": "no accessible ride was found",
    }
    source, violations, text = "template", (), template
    model_name = "none"
    try:
        model = model or from_env()
        model_name = model.name
        proposal = model.complete_json(contact_system_prompt(), json.dumps(record), CONTACT_MESSAGE_SCHEMA)
        candidate = proposal.get("message") if isinstance(proposal, dict) else None
        if isinstance(candidate, str) and candidate.strip():
            violations = tuple(contact_message_violations(candidate.strip(), owner, intake, facts, request_text))
            if not violations:
                source, text = "nano", candidate.strip()
        else:
            violations = ("no_message",)
    except IntakeError as exc:
        violations = ("model_unavailable",)
        log.warning("contact message: model unavailable, template used (%s)", exc.__class__.__name__)
    if source == "template" and violations:
        log.warning("contact message: model text refused for %s; template used", ", ".join(violations))
    metrics.record("contact_message", model=model_name, latency_ms=round((time.perf_counter() - started) * 1000), chars=len(text), source=source, violations=list(violations))
    return ContactMessage(text=text, source=source, violations=violations)


def _when(start: datetime) -> str:
    return f"{start:%a %b} {start.day}, {start.hour % 12 or 12}:{start:%M} {start:%p}"


def contact_message_violations(text: str, owner: UserRecord, intake: IntakeRequest, facts: ContactFacts, request_text: str | None) -> list[str]:
    """Why a candidate message may not go to the contact. Empty means it carries the four facts and nothing private.

    Kinds only, never values, so the result can be logged and recorded in the metrics.
    """
    found: list[str] = []
    lowered = text.lower()
    if len(text) > 320:
        found.append("too_long")
    # The four facts must be there, as given: a message that drops the clinic or the time is useless to the contact.
    hour_minute = f"{facts.slot_start.hour % 12 or 12}:{facts.slot_start:%M}"
    if facts.clinic.lower() not in lowered:
        found.append("missing_clinic")
    if hour_minute not in text:
        found.append("missing_time")
    if facts.address.split(",")[0].lower() not in lowered:
        found.append("missing_address")
    if "yes" not in lowered or "no" not in lowered:
        found.append("missing_reply_instruction")
    # It is Sarah's text: it opens with her name, never with the owner's ("Mary Sarah can you drive Mary..." was real output).
    if lowered.startswith(facts.owner_first_name.lower()) or facts.contact_first_name.lower() not in lowered[:40]:
        found.append("salutation")
    # Nothing private: the owner's own identifiers except the first name, the carrier, money, the dropped kinds.
    private = [v for v in _owner_values(owner) if v.lower() != facts.owner_first_name.lower()]
    if intake.insurance_carrier:
        private.append(intake.insurance_carrier)
    if any(v.lower() in lowered for v in private if len(v) >= 3):
        found.append("owner_record_value")
    if "$" in text or re.search(r"\b\d{2,4}\s*(?:dollars|bucks)\b", lowered) or (intake.budget_max and str(intake.budget_max) in re.sub(r"\d:\d\d", "", text)):
        found.append("money")
    # Identifier shapes, judged with the clinic address taken out so a street address is not mistaken for the owner's.
    stripped = lowered.replace(facts.address.lower(), "").replace(facts.address.split(",")[0].lower(), "")
    if backstop.detect_identifiers(stripped):
        found.append("identifier")
    if backstop.unsafe_terms(stripped, backstop.identifier_values(request_text or "")):
        found.append("sensitive_term")
    return found

