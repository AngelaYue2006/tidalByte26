"""POST /api/demo/reset (APP_ENV=development only) and GET /api/health."""

from __future__ import annotations

from fastapi import APIRouter, Request

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
