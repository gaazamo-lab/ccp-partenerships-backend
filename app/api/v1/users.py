"""
Staff account administration (System Administrator only) and the audit feed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_chain_is_intact, emit_audit
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, parse_uuid, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.rbac import ROLE_PERMISSIONS, P, Role
from app.core.security import hash_password, password_problems
from app.models.audit import AuditEvent
from app.models.users import User, UserSession
from app.schemas.auth import PasswordReset, RoleOut, UserCreate, UserOut, UserUpdate
from app.schemas.common import CamelModel, Envelope, PaginatedEnvelope, UtcDateTime, ok, paginated

router = APIRouter(tags=["Users & audit"])

_MANAGE = require_permission(P.USERS_MANAGE)
_AUDIT = require_permission(P.AUDIT_READ)


def _snapshot(user: User) -> dict:
    return {"email": user.email, "name": user.name, "role": user.role, "active": user.active}


def _check_password(password: str) -> None:
    problems = password_problems(password, min_length=get_settings().PASSWORD_MIN_LENGTH)
    if problems:
        raise ValidationFailed(problems[0], field_errors={"password": problems})


async def _get_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, parse_uuid(user_id, label="user"))
    if user is None:
        raise NotFound("That user does not exist.")
    return user


@router.get("/roles", response_model=Envelope[list[RoleOut]], summary="Roles and their permissions")
async def list_roles(identity: Identity = Depends(_MANAGE)):
    return ok([{"role": role, "permissions": sorted(ROLE_PERMISSIONS[role])} for role in Role.ALL])


@router.get("/users", response_model=Envelope[list[UserOut]], summary="List staff accounts")
async def list_users(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_MANAGE)):
    users = (await db.scalars(select(User).order_by(User.name))).all()
    return ok(list(users))


@router.post("/users", response_model=Envelope[UserOut], status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_MANAGE)):
    if await db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise Conflict("A user with that email already exists.", code="DUPLICATE_USER")
    _check_password(body.password)
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.USER_CREATED,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        identity=identity,
        after=_snapshot(user),
    )
    await db.commit()
    await db.refresh(user)
    return ok(user)


@router.patch("/users/{user_id}", response_model=Envelope[UserOut])
async def update_user(user_id: str, body: UserUpdate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_MANAGE)):
    user = await _get_user(db, user_id)
    if str(user.id) == identity.sub and (body.active is False or (body.role and body.role != user.role)):
        raise Conflict("You cannot deactivate or change the role of your own account.")
    before = _snapshot(user)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(user, name, value)
    if body.active is False or body.role is not None:
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await emit_audit(
        db,
        action=AuditAction.USER_UPDATED,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        identity=identity,
        before=before,
        after=_snapshot(user),
    )
    await db.commit()
    await db.refresh(user)
    return ok(user)


@router.post("/users/{user_id}/password", response_model=Envelope[UserOut], summary="Reset a user's password")
async def reset_password(
    user_id: str, body: PasswordReset, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_MANAGE)
):
    user = await _get_user(db, user_id)
    _check_password(body.password)
    user.password_hash = hash_password(body.password)
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_count = 0
    user.locked_until = None
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await emit_audit(
        db,
        action=AuditAction.USER_PASSWORD_RESET,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        identity=identity,
        summary="Password reset by administrator; sessions revoked.",
    )
    await db.commit()
    await db.refresh(user)
    return ok(user)


class AuditEventOut(CamelModel):
    sequence: int
    occurred_at: UtcDateTime
    action: str
    resource_type: str
    resource_id: str
    actor_email: str
    actor_role: str
    outcome: str
    summary: str
    correlation_id: str


class AuditIntegrityOut(CamelModel):
    intact: bool
    events: int


@router.get("/audit-events", response_model=PaginatedEnvelope[AuditEventOut], summary="Audit feed")
async def list_audit_events(
    resource_type: str | None = Query(None, alias="resourceType"),
    resource_id: str | None = Query(None, alias="resourceId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_AUDIT),
):
    query = select(AuditEvent)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditEvent.resource_id == resource_id)
    count = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(AuditEvent.sequence.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return paginated(list(rows), count=count, page=page, page_size=page_size)


@router.get("/audit-events/integrity", response_model=Envelope[AuditIntegrityOut], summary="Verify the hash chain")
async def audit_integrity(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_AUDIT)):
    events = await db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    return ok({"intact": await audit_chain_is_intact(db), "events": events})
