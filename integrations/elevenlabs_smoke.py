"""One authorized live adapter call using a backend-owned synthetic call context.

Prints receipt/status counts only. Never stores audio or prints transcript text.
"""

import argparse
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from dotenv import load_dotenv
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from integrations import elevenlabs_api, voice_elevenlabs
from integrations.elevenlabs_config import OPENING_LINE
from integrations.fixtures import read_fixture
from integrations.phone_policy import require_allowlisted
from integrations.types import CallSpec, Clinic, IntakeRequest, Window


def context(client, call_id):
    client.get("/api/session").raise_for_status()
    response = client.get("/api/tasks", params={"viewer_id": "mary", "limit": 200})
    response.raise_for_status()
    matches = [(task, call) for task in response.json() for call in task["calls"]
               if call["call_id"] == call_id]
    if (len(matches) != 1 or matches[0][1].get("result")
            or matches[0][1].get("status") == "done"):
        raise RuntimeError("Provide one fresh backend call context without an existing result")
    return matches[0]


def spec_for(task, call, destination):
    require_allowlisted(destination)
    clinics = read_fixture("clinics.json")["clinics"]
    matches = [clinic for clinic in clinics if clinic["name"] == call["clinic"]]
    if len(matches) != 1:
        raise RuntimeError("The smoke test requires a known synthetic clinic")
    clinic = Clinic.model_validate({k: v for k, v in matches[0].items() if k in Clinic.model_fields}).model_copy(update={"phone_e164": destination})
    return CallSpec(clinic=clinic, request=IntakeRequest.model_validate(task["intake"]),
                    windows=[Window.model_validate(w) for w in task["windows"]],
                    call_id=call["call_id"])


def run(args):
    if args.env_file.name != ".env" or not args.env_file.is_file():
        raise RuntimeError("Provide the existing ignored .env")
    load_dotenv(args.env_file, override=True)
    allowed = [p.strip() for p in os.environ["DEMO_PHONE_ALLOWLIST"].split(",") if p.strip()]
    if args.allowlist_index < 1 or args.allowlist_index > len(allowed):
        raise RuntimeError("Allowlist index is out of range")
    destination = allowed[args.allowlist_index - 1]
    require_allowlisted(destination)
    os.environ["VOICE_MODE"] = "live"
    transport = TwilioHttpClient(timeout=5, max_retries=0)
    transport.logger.disabled = True
    twilio = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"],
                    http_client=transport)
    twilio.calls.list(limit=1)  # fail before dialing if call control is inaccessible
    control = {"sid": None, "error": False, "status": None, "duration": None}
    watchdog = None
    original = elevenlabs_api.ElevenLabsClient.request

    def stop_call():
        try:
            call = twilio.calls(control["sid"]).fetch()
            require_allowlisted(call.to)
            if call.to != destination:
                raise RuntimeError("Call-control destination mismatch")
            if call.status not in {"completed", "busy", "failed", "no-answer", "canceled"}:
                twilio.calls(control["sid"]).update(status="completed")
            final = twilio.calls(control["sid"]).fetch()
            control["status"] = final.status
            control["duration"] = final.duration
        except Exception:  # noqa: BLE001 - never print credential-bearing SDK exceptions
            control["error"] = True
            print("Call-control verification failed; teammate must hang up immediately", flush=True)

    def watched_request(self, method, path, body=None):
        nonlocal watchdog
        data = original(self, method, path, body)
        if method == "POST" and path == "twilio/outbound-call":
            control["sid"] = data.get("callSid")
            if control["sid"]:
                watchdog = threading.Timer(40, stop_call)
                watchdog.start()
            else:
                print("No Twilio control receipt; teammate must hang up before one minute", flush=True)
        return data

    with httpx.Client(base_url=os.environ["PUBLIC_BASE_URL"].rstrip("/"), timeout=5) as client:
        task, call = context(client, args.call_id)
        spec = spec_for(task, call, destination)
        with patch.object(elevenlabs_api.ElevenLabsClient, "request", watched_request):
            handle = voice_elevenlabs.start_call(spec)
        print("Adapter accepted one live call; simulated=" + str(handle.simulated), flush=True)
        if watchdog:
            watchdog.join()  # bounds the connected call; SDK requests have five-second timeouts
        else:
            raise RuntimeError("Missing call-control receipt; verify hangup before retrying")
        if control["error"]:
            raise RuntimeError("Call duration could not be verified")
        print("Twilio terminal status:", control["status"], "duration seconds:", control["duration"], flush=True)
        deadline = time.monotonic() + 45
        lines, results = [], []
        while time.monotonic() < deadline:
            response = client.get("/api/tasks/" + task["id"] + "/events", params={"viewer_id": "mary"})
            response.raise_for_status()
            events = [e for e in response.json() if e.get("call_id") == args.call_id]
            lines = [e for e in events if e["type"] == "transcript"]
            results = [e for e in events if e["type"] == "call_result"]
            if lines and results:
                break
            time.sleep(2)
        agents = [line for line in lines if line.get("speaker") == "agent"]
        print("Backend transcript events:", len(lines), "call_result events:", len(results))
        print("First agent line discloses AI:", bool(agents and agents[0]["text"].startswith(OPENING_LINE)))
        return 0 if lines and len(results) == 1 and agents and agents[0]["text"].startswith(OPENING_LINE) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--call-id", required=True)
    parser.add_argument("--allowlist-index", type=int, required=True, help="One-based, explicitly authorized destination")
    args = parser.parse_args()
    try:
        return run(args)
    except RuntimeError as error:
        print("Smoke test stopped:", str(error))
    except Exception as error:  # noqa: BLE001 - SDK/HTTP errors can contain secrets
        print("Smoke test stopped:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
