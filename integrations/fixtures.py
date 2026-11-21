"""Read synthetic backend fixtures without depending on backend Python modules."""

import json
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "backend" / "fixtures"


def read_fixture(name: str) -> dict:
    try:
        return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError(f"Synthetic fixture unavailable: {name}") from None
