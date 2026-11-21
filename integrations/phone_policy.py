"""Shared phone boundary for demo adapters, including simulated inbound SMS."""

import os
import re


def require_allowlisted(phone: str) -> None:
    allowed = {p.strip() for p in os.getenv("DEMO_PHONE_ALLOWLIST", "").split(",")}
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone) or phone not in allowed:
        raise RuntimeError("UNVERIFIED_SENDER: phone is not on the demo allowlist")
