"""GET /api/live?viewer_id -> Server-Sent Events. Snapshot first, then events, heartbeat every 15 s. Poll fallback via LIVE_STREAM_MODE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.events import resolve_viewer
from app.projections import snapshot

router = APIRouter(prefix="/api", tags=["live"])

HEARTBEAT_SECONDS = 15.0
# Tunnels buffer SSE unless told not to (CLAUDE.md, Common issues).
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def format_sse(data: dict, event_id: int | None) -> str:
    """One SSE message: an `id:` line when the event has one, then a single `data:` line of JSON."""
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/live")
async def live(request: Request, viewer_id: str = Query(min_length=1)) -> StreamingResponse:
    engine = request.app.state.engine
    bus = request.app.state.bus
    heartbeat = float(getattr(request.app.state, "heartbeat_seconds", HEARTBEAT_SECONDS))
    with Session(engine) as session:
        viewer = resolve_viewer(session, viewer_id)
    sub = bus.subscribe(viewer)  # subscribe before the snapshot so nothing in between is lost

    async def stream() -> AsyncIterator[str]:
        try:
            snap = snapshot(engine, viewer)
            yield format_sse(snap, snap.pop("last_event_id", None))
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield format_sse({"type": "heartbeat"}, None)
                    continue
                yield format_sse(event, event["id"])
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
