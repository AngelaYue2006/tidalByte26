"""POST /api/demo/reset (APP_ENV=development only, app/seed.py does the work) and GET /api/health."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import seed
from app.config import MODEL_IDS, Settings

router = APIRouter(prefix="/api", tags=["demo"])


def health_payload(settings: Settings, version: str) -> dict:
    """Adapter modes and which model IDs are configured. No keys, tokens, phone numbers or URLs."""
    return {
        "status": "ok",
        "version": version,
        "app_env": settings.app_env,
        "timezone": settings.app_timezone,
        "modes": settings.modes,
        "models": {name: settings.model_id(name) for name in MODEL_IDS},
        "allowlist_size": len(settings.demo_phone_allowlist),
    }


@router.get("/health")
def health(request: Request) -> dict:
    return health_payload(request.app.state.settings, request.app.version)


@router.post("/demo/reset")
async def demo_reset(request: Request) -> dict:
    """Development only: stop every pipeline, wipe every table, reseed the contacts and two past runs (T12).

    Runs on the event loop so the pipeline's asyncio tasks can be cancelled from the loop that owns them.
    """
    settings = request.app.state.settings
    if not settings.is_development:
        raise HTTPException(status_code=403, detail="demo reset is only available when APP_ENV=development")
    state = request.app.state
    return seed.reset(state.engine, state.pipeline, state.bus)
