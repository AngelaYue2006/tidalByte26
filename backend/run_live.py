"""Start the opt-in single-call backend using an existing ignored .env.

Run from the repo root: python -m backend.run_live --env-file PATH --allowlist-index 1
The public tunnel and the frontend must both point at THIS backend.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def configure(env_file: Path, index: int):
    if env_file.name != ".env" or not env_file.is_file():
        raise RuntimeError("Provide an existing ignored .env file")
    load_dotenv(env_file, override=True)
    allowed = [phone.strip() for phone in os.getenv("DEMO_PHONE_ALLOWLIST", "").split(",") if phone.strip()]
    if not 1 <= index <= len(allowed):
        raise RuntimeError("Choose a valid one-based allowlist index")
    target = allowed[index - 1]
    if target == os.getenv("TWILIO_PHONE_NUMBER"):
        raise RuntimeError("Choose a teammate recipient, not the Twilio sender")
    os.environ["VOICE_MODE"] = "live"
    os.environ["DEMO_VOICE_TARGET"] = target
    # A separate local database preserves the existing demo's tasks and receipts.
    database = Path(__file__).resolve().parents[1] / "lifeline-live.db"
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--allowlist-index", type=int, required=True)
    args = parser.parse_args()
    try:
        configure(args.env_file, args.allowlist_index)
    except RuntimeError as error:
        parser.error(str(error))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import uvicorn

    # No reload: restarting an in-flight task loses its wait, but not its dial receipt.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
