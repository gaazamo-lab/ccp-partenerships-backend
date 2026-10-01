"""
Email + password sign-in, session lookup and sign-out.

Contract (matches `createAuthClient` in `@partner-crm/auth`):
- `POST /auth/login` `{email, password}` → `{user}` and sets the session cookie.
- `GET /auth/session` → `{user}` or `401`.
- `POST /auth/logout` → `204` and clears the cookie.

Failed attempts count per account; after `LOGIN_MAX_FAILED_ATTEMPTS` the account
locks for `LOGIN_LOCKOUT_MINUTES`. Unknown emails and wrong passwords return the
same message and take the same time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import (
    Identity,
    clear_session_cookie,
    create_session,
    get_current_identity,
    identity_for,
    resolve_session,
    set_session_cookie,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Unauthorized, ValidationFailed
from app.core.security import hash_password, needs_rehash, password_problems, verify_password
from app.models.users import User, UserSession
from app.schemas.auth import ChangePasswordRequest, LoginRequest, SessionResponse

router = APIRouter(prefix="/auth", tags=["Auth"])

_INVALID = "The email or password is incorrect."


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.post("/login", response_model=SessionResponse, summary="Sign in with email and password")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    now = datetime.now(UTC)
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))

    if user is not None and user.locked_until is not None and _aware(user.locked_until) > now:
        await emit_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            resource_type=ResourceType.USER,
            resource_id=user.id,
            summary="Sign-in refused: account locked.",
            outcome="denied",
        )
        await db.commit()
        raise Unauthorized(
            "Too many failed attempts. Try again later or ask an administrator to unlock your account.",
            code="ACCOUNT_LOCKED",
        )

    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.active:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                user.failed_login_count = 0
            await emit_audit(
                db,
                action=AuditAction.LOGIN_FAILED,
                resource_type=ResourceType.USER,
                resource_id=user.id,
                summary="Sign-in failed." if user.active else "Sign-in refused: account inactive.",
                outcome="denied",
            )
            await db.commit()
        raise Unauthorized(_INVALID, code="INVALID_CREDENTIALS")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    token = await create_session(db, user, request, settings)
    identity = identity_for(user, request=request)
    await emit_audit(
        db,
        action=AuditAction.LOGIN_SUCCEEDED,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        identity=identity,
        summary="Signed in.",
    )
    await db.commit()
    set_session_cookie(response, token, settings)
    return {"user": user}


@router.get("/session", response_model=SessionResponse, summary="Current session user")
async def session(request: Request, db: AsyncSession = Depends(get_db)):
    current = await resolve_session(db, request, get_settings())
    if current is None:
        raise Unauthorized("No active session.", code="SESSION_REQUIRED")
    return {"user": current.user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    current = await resolve_session(db, request, settings)
    if current is not None:
        current.revoked_at = datetime.now(UTC)
        await emit_audit(
            db,
            action=AuditAction.LOGOUT,
            resource_type=ResourceType.USER,
            resource_id=current.user_id,
            identity=identity_for(current.user, request=request),
            summary="Signed out.",
        )
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change my password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity()),
):
    settings = get_settings()
    user = await db.get(User, uuid.UUID(identity.sub))
    if user is None or not verify_password(body.current_password, user.password_hash):
        raise ValidationFailed(
            "Your current password is incorrect.",
            field_errors={"currentPassword": ["Your current password is incorrect."]},
        )
    problems = password_problems(body.new_password, min_length=settings.PASSWORD_MIN_LENGTH)
    if problems:
        raise ValidationFailed(problems[0], field_errors={"newPassword": problems})
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    # Every other session ends when the password changes.
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.id != uuid.UUID(identity.session_id))
        .values(revoked_at=datetime.now(UTC))
    )
    await emit_audit(
        db,
        action=AuditAction.PASSWORD_CHANGED,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        identity=identity,
        summary="Password changed; other sessions revoked.",
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
