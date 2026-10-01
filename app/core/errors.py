"""
Error model and exception handlers.

Every error leaves the API in one stable shape, which the frontend `ApiErrorBody`
type mirrors:

    {"code": "...", "message": "...", "fieldErrors": {...}, "correlationId": "...", "retryable": false}

Domain code raises `AppError` (or a subclass); routers never hand-build error
responses.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A business error with an HTTP status, a stable code and a user-readable message."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        field_errors: dict[str, list[str]] | None = None,
        extra: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.field_errors = field_errors or {}
        self.extra = extra or {}
        self.retryable = retryable


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class TooManyRequests(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    field_errors: dict[str, list[str]] | None = None,
    extra: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "fieldErrors": field_errors or {},
        "correlationId": _correlation_id(request),
        "retryable": retryable,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request,
        exc.status_code,
        exc.code,
        exc.message,
        field_errors=exc.field_errors,
        extra=exc.extra,
        retryable=exc.retryable,
    )


def _field_name(loc: tuple[Any, ...]) -> str:
    parts = [str(part) for part in loc if part not in ("body", "query", "path")]
    return ".".join(parts) or "request"


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors: dict[str, list[str]] = {}
    for error in exc.errors():
        message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
        field_errors.setdefault(_field_name(tuple(error.get("loc", ()))), []).append(message)
    first = next(iter(field_errors.items()), ("request", ["Invalid request."]))
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        f"{first[0]}: {first[1][0]}",
        field_errors=field_errors,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "error_code", None) or f"HTTP_{exc.status_code}"
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(request, exc.status_code, code, message)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("request.unhandled correlation_id=%s", _correlation_id(request))
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
        retryable=True,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
