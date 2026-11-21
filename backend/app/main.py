"""FastAPI app factory. Mounts routers from app.routers and the SSE stream. Owner: Person 1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.routers import demo, llm_proxy

VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
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
    app.include_router(demo.router)
    app.include_router(llm_proxy.router)
    return app


app = create_app()
