"""Nemotron Nano, 4-bit, local via Ollama. redact(utterance, user) -> IntakeRequest; contact_message(task, contact) -> str. The raw utterance must never leave this module for a network call."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from app import metrics
from app.nemotron import intake_backstop as backstop
from app.nemotron.prompts import INTAKE_OUTPUT_SCHEMA, intake_system_prompt
from app.nemotron.types import DROPPABLE_FIELDS, IntakeRequest, TimeRange, UserRecord

log = logging.getLogger(__name__)

INTAKE_INCOMPLETE = "INTAKE_INCOMPLETE"


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


def from_env() -> OllamaClient:
    """Read OLLAMA_BASE_URL and NEMOTRON_NANO_TAG. No model tag is invented."""
    return OllamaClient(os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"), os.environ.get("NEMOTRON_NANO_TAG"))


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

    if backstop.unsafe_terms(data["care_type"], leaks) or re.search(r"\d", data["care_type"]):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: care type carried something that must not leave the device")

    carrier = data.get("insurance_carrier")
    if isinstance(carrier, str) and (backstop.unsafe_terms(carrier, leaks) or re.search(r"\d", carrier) or len(carrier.split()) > 4):
        data["insurance_carrier"] = None
        log.warning("intake: insurance carrier replaced with null after a leak check")

    area = data.get("search_area") or "near home"
    if backstop.unsafe_terms(area, leaks) or re.search(r"\d", area) or backstop.detect_identifiers(area) or len(area.split()) > 4:
        data["search_area"] = "near home"
        for name in ("address", "patient_name"):
            if name not in data["dropped_fields"] and (name == "address") == bool(backstop.detect_identifiers(area) or re.search(r"\d", area)):
                data["dropped_fields"].append(name)
                break
        log.warning("intake: search area replaced with 'near home' after a leak check")

    data["dropped_fields"].sort(key=DROPPABLE_FIELDS.index)
    serialized = json.dumps(data).lower()
    if any(value.lower() in serialized for value in leaks if len(value) >= 3):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: an identifier survived redaction")
    return IntakeRequest.model_validate(data)
