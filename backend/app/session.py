"""The shared dashboard session cookie (docs/ARCHITECTURE.md, REST interface): GET /api/session issues it, require_session guards every read route.

Hackathon auth, not identity: the cookie proves the browser went through the dashboard, viewer_id picks the role.
The token is `<nonce>.<hmac_sha256(nonce, DASHBOARD_SESSION_SECRET)>`; in development with no secret set the app
uses a random per-process secret, so cookies die with the process.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import APIRouter, HTTPException, Request, Response

COOKIE = "lifeline_session"
router = APIRouter(prefix="/api", tags=["session"])


def _sign(nonce: str, secret: str) -> str:
    return hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def issue(secret: str) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_sign(nonce, secret)}"


def is_valid(token: str | None, secret: str) -> bool:
    if not token:
        return False
    nonce, _, signature = token.partition(".")
    return bool(nonce and signature) and hmac.compare_digest(_sign(nonce, secret), signature)


def require_session(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries a valid session cookie."""
    if not is_valid(request.cookies.get(COOKIE), request.app.state.session_secret):
        raise HTTPException(status_code=401, detail="dashboard session required: GET /api/session first")


@router.get("/session")
def session(request: Request, response: Response) -> dict:
    """Issue the cookie, or keep a valid one. The dashboard calls this once before opening /api/live."""
    secret = request.app.state.session_secret
    if not is_valid(request.cookies.get(COOKIE), secret):
        response.set_cookie(COOKIE, issue(secret), httponly=True, samesite="lax", path="/")
    return {"ok": True}
