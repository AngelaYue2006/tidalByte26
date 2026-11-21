"""Nemotron Nano, 4-bit, local via Ollama. redact(utterance, user) -> IntakeRequest; contact_message(task, contact) -> str. The raw utterance must never leave this module for a network call."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Protocol
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


class OllamaClient:
    """The only network client in this module. Talks to OLLAMA_BASE_URL and nowhere else."""

    def __init__(self, base_url: str, model_tag: str | None, timeout_s: float = 60.0) -> None:
        if not model_tag:
            raise IntakeError("NEMOTRON_NANO_TAG is not set; the intake model has no default")
        self.base_url = base_url.rstrip("/")
        self.name = model_tag
        self.timeout_s = timeout_s

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.name,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout_s)
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
    request = _scrub_leaks(utterance, request)
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
    care_type = str(proposal.get("care_type") or "").strip().lower().rstrip(".")
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


def _scrub_leaks(utterance: str, request: IntakeRequest) -> IntakeRequest:
    """Last line of defence: no identifier value from the utterance may appear in the request."""
    leaks = backstop.identifier_values(utterance)
    if not leaks:
        return request
    data = request.model_dump()
    serialized = json.dumps(data).lower()
    if not any(value.lower() in serialized for value in leaks):
        return request
    for field in ("insurance_carrier", "search_area"):
        value = data.get(field)
        if isinstance(value, str) and any(leak.lower() in value.lower() for leak in leaks):
            data[field] = None if field == "insurance_carrier" else "near home"
            log.warning("intake: dropped a leaked identifier from %s", field)
    if any(leak.lower() in data["care_type"].lower() for leak in leaks):
        raise IntakeError(f"{INTAKE_INCOMPLETE}: care type carried an identifier")
    return IntakeRequest.model_validate(data)
