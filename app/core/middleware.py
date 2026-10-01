"""
HTTP middleware: correlation IDs, CSRF origin checks and security headers.

CSRF: sessions are HTTP-only, SameSite cookies. As a second line of defence,
every state-changing request must carry an `Origin` (or `Referer`) that is on
`ALLOWED_ORIGINS` or is the API's own origin. Requests with neither header
(server-to-server tools, tests) are allowed only for safe methods.
"""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
        # Only accept caller-supplied IDs that look like IDs, never arbitrary text.
        correlation_id = (
            incoming if incoming and len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        )
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def _origin_of(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)

        settings = get_settings()
        origin = request.headers.get("origin") or _origin_of(request.headers.get("referer", ""))
        if origin:
            own = f"{request.url.scheme}://{request.url.netloc}"
            allowed = {o.rstrip("/") for o in settings.ALLOWED_ORIGINS} | {own}
            if origin.rstrip("/") not in allowed:
                logger.warning("csrf.origin_rejected origin=%s path=%s", origin, request.url.path)
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": "CSRF_ORIGIN_REJECTED",
                        "message": "This request did not come from an allowed origin.",
                        "fieldErrors": {},
                        "correlationId": getattr(request.state, "correlation_id", ""),
                        "retryable": False,
                    },
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response
