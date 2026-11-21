"""FastAPI app factory. Mounts routers from app.routers and the SSE stream. Owner: Person 1."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import session
from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.events import EventBus
from app.nemotron import local_intake
from app.routers import demo, live, tasks

VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Settings come from .env unless a test passes them in. Startup fails loudly on a missing live value."""
    settings = settings or load_settings()
    settings.validate_startup()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(engine)
        # Load Nano now, off the event loop, so the first intake is the 2 s one and not the 10 s one (#77).
        app.state.warm_up_thread = local_intake.warm_up_in_background(settings.ollama_base_url, settings.nemotron_nano_tag)
        yield
        engine.dispose()

    app = FastAPI(title="LifeLine", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.bus = EventBus()
    # Development without a configured secret gets a per-process one; validate_startup requires it elsewhere.
    app.state.session_secret = settings.dashboard_session_secret or secrets.token_hex(32)
    app.state.heartbeat_seconds = live.HEARTBEAT_SECONDS
    app.include_router(demo.router)
    app.include_router(session.router)
    app.include_router(live.router)
    app.include_router(tasks.router)
    return app


app = create_app()
