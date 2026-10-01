"""
Email + password authentication with server-side sessions.

The browser holds an opaque, HTTP-only, SameSite session cookie. Each request
resolves that cookie to a `UserSession` row (by SHA-256 digest), enforces idle
and absolute expiry, slides the idle window, and builds an `Identity`.
Routers depend only on `Identity` and the `require_*` factories — never on the
cookie or the ORM user — so the mechanism can change without touching them.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.rbac import has_permission, permissions_for_role
from app.core.security import new_session_token, token_digest
from app.models.users import User, UserSession

logger = logging.getLogger(__name__)


@dataclass
class Identity:
    sub: str
    email: str
    name: str
    role: str
    permissions: set[str] = field(default_factory=set)
    session_id: str = ""
    source_ip: str = ""
    correlation_id: str = ""

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.permissions, permission)

    @property
    def display(self) -> str:
        return self.name or self.email


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def identity_for(user: User, *, request: Request | None = None, session_id: str = "") -> Identity:
    return Identity(
        sub=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        permissions=permissions_for_role(user.role),
        session_id=session_id,
        source_ip=client_ip(request) if request else "",
        correlation_id=getattr(request.state, "correlation_id", "") if request else "",
    )


async def create_session(db: AsyncSession, user: User, request: Request, settings: Settings) -> str:
    """Persist a new session and return the raw token for the cookie."""
    token = new_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_digest=token_digest(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.SESSION_ABSOLUTE_HOURS),
            ip_address=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:512],
        )
    )
    return token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_ABSOLUTE_HOURS * 3600,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


async def resolve_session(db: AsyncSession, request: Request, settings: Settings) -> UserSession | None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token or len(token) > 128:
        return None
    session = await db.scalar(select(UserSession).where(UserSession.token_digest == token_digest(token)))
    if session is None or session.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    idle_limit = _aware(session.last_seen_at) + timedelta(minutes=settings.SESSION_IDLE_MINUTES)
    if _aware(session.expires_at) <= now or idle_limit <= now or not session.user.active:
        return None
    # Slide the idle window at most once a minute to avoid a write per request.
    if now - _aware(session.last_seen_at) > timedelta(minutes=1):
        session.last_seen_at = now
        await db.commit()
    return session


async def _get_identity(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Identity:
    settings = get_settings()
    session = await resolve_session(db, request, settings)
    if session is None:
        raise Unauthorized("Your session has ended. Sign in again.", code="SESSION_REQUIRED")
    return identity_for(session.user, request=request, session_id=str(session.id))


def get_current_identity() -> Callable[..., Awaitable[Identity]]:
    """The dependency tests override: `app.dependency_overrides[get_current_identity()] = ...`."""
    return _get_identity


def require_permission(permission: str) -> Callable[..., Awaitable[Identity]]:
    async def dependency(identity: Identity = Depends(_get_identity)) -> Identity:
        if not identity.has_permission(permission):
            logger.warning("auth.permission_denied sub=%s required=%s", identity.sub, permission)
            raise Forbidden("You do not have permission to do this.", code="PERMISSION_DENIED")
        return identity

    return dependency


def require_any_permission(*permissions: str) -> Callable[..., Awaitable[Identity]]:
    async def dependency(identity: Identity = Depends(_get_identity)) -> Identity:
        if not any(identity.has_permission(p) for p in permissions):
            logger.warning("auth.permission_denied sub=%s required_any=%s", identity.sub, permissions)
            raise Forbidden("You do not have permission to do this.", code="PERMISSION_DENIED")
        return identity

    return dependency


def parse_uuid(value: str, *, label: str = "record") -> uuid.UUID:
    from app.core.errors import NotFound

    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise NotFound(f"That {label} does not exist.") from exc
