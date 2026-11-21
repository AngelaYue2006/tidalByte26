"""FastAPI app factory. Mounts routers from app.routers and the SSE stream. Owner: Person 1."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import session
from app.adapters import Deps, build_deps
from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.events import EventBus
from app.orchestrator import Pipeline
from app.routers import approvals, contacts, demo, live, requests, tasks, webhooks

VERSION = "0.1.0"


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    """Build the app. Settings come from .env unless a test passes them in. Startup fails loudly on a missing live value."""
    settings = settings or load_settings()
    settings.validate_startup()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(title="LifeLine", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.bus = EventBus()
    # Development without a configured secret gets a per-process one; validate_startup requires it elsewhere.
    app.state.session_secret = settings.dashboard_session_secret or secrets.token_hex(32)
    app.state.heartbeat_seconds = live.HEARTBEAT_SECONDS
    app.state.pipeline = Pipeline(deps or build_deps(settings), engine, app.state.bus)
    app.include_router(demo.router)
    app.include_router(session.router)
    app.include_router(live.router)
    app.include_router(tasks.router)
    app.include_router(requests.router)
    app.include_router(approvals.router)
    app.include_router(contacts.router)
    app.include_router(webhooks.router)
    return app


app = create_app()
