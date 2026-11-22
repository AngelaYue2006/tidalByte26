"""GranniAI backend package.

The orchestrator reaches vendors only through the sibling top-level package `integrations/` (docs/ARCHITECTURE.md).
`cd backend && uvicorn app.main:app` and `pytest backend` put only `backend/` on the path, so the repo root is added
here once, when it is not already importable.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)
