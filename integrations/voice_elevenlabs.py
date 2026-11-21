"""Live outbound discovery calls; mock replay is integrations.voice_mock (#13).

Backend owns approval, durable idempotency, external_ref storage and callbacks.
This adapter never imports backend code or writes state.
"""

import json
import os
import re

from integrations import elevenlabs_api
from integrations.phone_policy import require_allowlisted
from integrations.types import CallHandle, CallSpec, Confirmation


def _mode():
    mode = os.getenv("VOICE_MODE", "mock")
    if mode not in {"mock", "live"}:
        raise RuntimeError("VOICE_MODE must be mock or live")
    return mode


def _mock(method, *args):
    from integrations import voice_mock

    callback = getattr(voice_mock, method, None)
    if callback is None:
        raise RuntimeError(
            "VOICE_MODE=mock requires the receptionist adapter (#13); use the fixture mock pipeline meanwhile"
        )
    if not callable(callback):
        raise TypeError("VOICE_MODE=mock requires a callable receptionist adapter")
    return callback(*args)


def start_call(call: CallSpec) -> CallHandle:
    require_allowlisted(call.clinic.phone_e164)
    if _mode() == "mock":
        return _mock("start_call", call)
    with elevenlabs_api.ElevenLabsClient() as client:
        client.preflight()
        variables = {
            "call_id": call.call_id,
            "clinic_name": call.clinic.name,
            "care_type": call.request.care_type,
            "budget_max": call.request.budget_max
            if call.request.budget_max is not None
            else "",
            "insurance_carrier": call.request.insurance_carrier or "",
            "windows": json.dumps(
                [window.model_dump(mode="json") for window in call.windows]
            ),
        }
        body = {
            "agent_id": client.settings.agent_id,
            "agent_phone_number_id": client.settings.phone_id,
            "to_number": call.clinic.phone_e164,
            "call_recording_enabled": False,
            "conversation_initiation_client_data": {
                "custom_llm_extra_body": {
                    "call_id": call.call_id,
                    "proxy_secret": client.settings.proxy_secret,
                },
                "dynamic_variables": variables,
            },
        }
        # Settings checks may take time; recheck the actual destination at dial time.
        require_allowlisted(body["to_number"])
        data = client.request("POST", "twilio/outbound-call", body)
    reference = data.get("conversation_id")
    if (
        data.get("success") is not True
        or not isinstance(reference, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", reference)
    ):
        raise RuntimeError(
            "ElevenLabs did not return an accepted call receipt; call outcome unverified"
        )
    return CallHandle(call_id=call.call_id, external_ref=reference, simulated=False)


def confirm_booking(call: CallSpec, slot) -> Confirmation:
    require_allowlisted(call.clinic.phone_e164)
    if _mode() == "mock":
        return _mock("confirm_booking", call, slot)
    # The landed proxy explicitly forbids booking. Do not originate another
    # discovery call, infer confirmation from speech, or return a fake receipt.
    raise RuntimeError(
        "Live booking is unavailable until the backend provides approved booking "
        "context, a booking-capable proxy prompt and structured confirmation evidence"
    )
