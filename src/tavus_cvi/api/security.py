"""Interview ownership is an opaque cookie capability, not a public UUID."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

COOKIE = "tavus_interview"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def require_owner(request: Request, interview_id: UUID) -> None:
    token = request.cookies.get(COOKIE, "")
    owned = request.app.state.repository.owned_interview(token) if token else None
    if owned != interview_id:
        raise HTTPException(403, "This interview belongs to another session")


class CandidateSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in {"POST", "PUT", "DELETE", "PATCH"} and request.url.path.startswith(
            "/api/"
        ):
            origin = request.headers.get("origin")
            if origin not in request.app.state.settings.allowed_origins:
                return Response("Origin is not allowed", status_code=403)
            if request.headers.get("x-requested-with") != "tavus-interview":
                return Response("Missing CSRF request header", status_code=403)
        return await call_next(request)
