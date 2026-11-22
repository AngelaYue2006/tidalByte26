"""Read-only voice readiness check. Never originates a call or changes an agent."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from integrations.elevenlabs_api import ElevenLabsClient


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.env_file.name != ".env" or not args.env_file.is_file():
            raise RuntimeError("Provide the existing local .env file")
        load_dotenv(args.env_file, override=True)
        with ElevenLabsClient() as client:
            client.preflight()
        print("PASS: agent and imported Twilio number passed read-only preflight; no call placed")
        return 0
    except RuntimeError as error:
        # Only sanitized configuration/transport failures cross our HTTP boundary.
        print("Voice preflight blocked:", str(error))
    except Exception as error:  # noqa: BLE001 - never echo credential-bearing failures
        print("Voice preflight stopped:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
