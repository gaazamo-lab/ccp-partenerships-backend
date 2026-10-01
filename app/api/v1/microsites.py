"""
S091 Donor Microsite Builder endpoints (rules: partner-crm
`docs/architecture/new-module-rules.md`, S091).

Restricted sites are unlocked with an access code; a successful unlock sets a
signed, HTTP-only cookie scoped to that site and bound to the current code, so
changing the code revokes every earlier unlock.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit, enqueue
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, client_ip, parse_uuid, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.core.rate_limit import hit
from app.core.rbac import P
from app.core.security import hash_password, verify_password
from app.models.base import utcnow
from app.models.microsites import Microsite, MicrositeReview, MicrositeStatus, MicrositeTemplate
from app.models.stakeholders import Stakeholder
from app.schemas.common import Envelope, ok
from app.schemas.microsites import (
    AccessIn,
    ArchiveIn,
    CreateIn,
    MicrositeOut,
    PublicMicrositeOut,
    ReviewIn,
    ReviewOut,
    TemplateOut,
    UnlockIn,
    UpdateIn,
    ViewIn,
)

router = APIRouter(tags=["S091 Donor microsites"])

_READ = require_permission(P.MICROSITES_READ)
_WRITE = require_permission(P.MICROSITES_WRITE)
_REVIEW = require_permission(P.MICROSITES_REVIEW)
_PUBLISH = require_permission(P.MICROSITES_PUBLISH)

M = MicrositeStatus
UNLOCK_HOURS = 8
_EMPTY_BLOCK = {
    "heading": "",
    "body": "",
    "assetRefs": [],
    "metrics": [],
    "allocations": [],
    "currency": "GHS",
    "links": [],
    "attribution": "",
}


def serialize(site: Microsite) -> dict:
    return {
        "id": site.id,
        "slug": site.slug,
        "title": site.title,
        "tagline": site.tagline,
        "purpose": site.purpose,
        "template_id": site.template_id,
        "status": site.status,
        "access": site.access,
        "audience_stakeholder_ids": [str(x) for x in site.audience_stakeholder_ids],
        "accent_color": site.accent_color,
        "owner": site.owner,
        "blocks": site.blocks,
        "version": site.version,
        "published_version": site.published_version,
        "published_at": site.published_at,
        "archived_at": site.archived_at,
        "archive_ref": site.archive_ref,
        "analytics": {
            "views": site.views,
            "unique_visitors": site.unique_visitors,
            "average_seconds": site.total_seconds // site.views if site.views else 0,
            "downloads": site.downloads,
            "last_viewed_at": site.last_viewed_at,
        },
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def serialize_public(site: Microsite) -> dict:
    return {
        "slug": site.slug,
        "title": site.published_title or site.title,
        "tagline": site.published_tagline or "",
        "purpose": site.purpose,
        "accent_color": site.accent_color,
        "blocks": site.published_blocks or [],
        "published_at": site.published_at,
    }


async def _site(db: AsyncSession, site_id: str) -> Microsite:
    site = await db.get(Microsite, parse_uuid(site_id, label="microsite"))
    if site is None:
        raise NotFound("That microsite does not exist.", code="MICROSITE_NOT_FOUND")
    return site


async def _slug_free(db: AsyncSession, slug: str, except_id=None) -> None:
    other = await db.scalar(select(Microsite).where(Microsite.slug == slug))
    if other is not None and other.id != except_id:
        raise Conflict(
            "Another microsite already uses that address.", code="DUPLICATE_SLUG", field_errors={"slug": ["Already in use."]}
        )


async def _audit(db, identity, action, site, summary="", before=None):
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.MICROSITE,
        resource_id=site.id,
        identity=identity,
        summary=summary,
        before=before,
        after={"status": site.status, "version": site.version, "access": site.access},
    )


# ── Templates & administration ──


@router.get("/microsite-templates", response_model=Envelope[list[TemplateOut]])
async def list_templates(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return ok(list((await db.scalars(select(MicrositeTemplate).order_by(MicrositeTemplate.name))).all()))


@router.get("/microsites", response_model=Envelope[list[MicrositeOut]])
async def list_microsites(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    rows = (await db.scalars(select(Microsite).order_by(Microsite.updated_at.desc()))).all()
    return ok([serialize(r) for r in rows])


@router.get("/microsites/{site_id}", response_model=Envelope[MicrositeOut])
async def get_microsite(site_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return ok(serialize(await _site(db, site_id)))


@router.post("/microsites", response_model=Envelope[MicrositeOut], status_code=201)
async def create_microsite(body: CreateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    template = await db.get(MicrositeTemplate, body.template_id)
    if template is None:
        raise ValidationFailed("Choose a template from the library.", field_errors={"templateId": ["Unknown template."]})
    await _slug_free(db, body.slug)
    blocks = [{"id": f"blk-{uuid.uuid4().hex[:10]}", "type": block_type, **_EMPTY_BLOCK} for block_type in template.block_types]
    if blocks and blocks[0]["type"] == "HERO":
        blocks[0]["heading"] = body.title
        blocks[0]["body"] = body.tagline
    site = Microsite(
        slug=body.slug,
        title=body.title,
        tagline=body.tagline,
        purpose=body.purpose,
        template_id=template.id,
        owner=body.owner,
        blocks=blocks,
        status=M.DRAFT,
        access="PUBLIC",
    )
    db.add(site)
    await db.flush()
    await _audit(db, identity, AuditAction.MICROSITE_CREATED, site)
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.put("/microsites/{site_id}", response_model=Envelope[MicrositeOut])
async def update_microsite(
    site_id: str, body: UpdateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    site = await _site(db, site_id)
    if site.status not in M.EDITABLE:
        raise Conflict("This microsite cannot be edited in its current state.", code="MICROSITE_LOCKED")
    await _slug_free(db, body.slug, except_id=site.id)
    ids = [b.id for b in body.blocks]
    if len(ids) != len(set(ids)):
        raise ValidationFailed("Block IDs must be unique.")
    before = {"status": site.status, "version": site.version}
    site.title, site.slug, site.tagline, site.accent_color = body.title, body.slug, body.tagline, body.accent_color
    site.blocks = [b.model_dump(by_alias=True) for b in body.blocks]
    site.version += 1
    site.status = M.DRAFT  # approval covers a specific version; any edit needs a fresh review
    await _audit(db, identity, AuditAction.MICROSITE_UPDATED, site, before=before)
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.put("/microsites/{site_id}/access", response_model=Envelope[MicrositeOut])
async def set_access(site_id: str, body: AccessIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    site = await _site(db, site_id)
    if site.status == M.ARCHIVED:
        raise Conflict("Archived microsites cannot change access.", code="MICROSITE_ARCHIVED")
    if body.access in ("PASSWORD", "NAMED_AUDIENCE"):
        if body.access_code:
            if len(body.access_code) < 8:
                raise ValidationFailed("Access codes are at least 8 characters.", field_errors={"accessCode": ["Too short."]})
            site.access_code_hash = hash_password(body.access_code)
        elif site.access_code_hash is None:
            raise ValidationFailed("Set an access code for a restricted microsite.", field_errors={"accessCode": ["Required."]})
    if body.access == "NAMED_AUDIENCE":
        if not body.audience_stakeholder_ids:
            raise ValidationFailed("Name at least one S081 stakeholder.", field_errors={"audienceStakeholderIds": ["Required."]})
        for raw in body.audience_stakeholder_ids:
            if await db.get(Stakeholder, parse_uuid(raw, label="stakeholder")) is None:
                raise ValidationFailed(
                    f"{raw} is not an S081 stakeholder.", field_errors={"audienceStakeholderIds": ["Unknown stakeholder."]}
                )
    before = {"access": site.access}
    site.access = body.access
    site.audience_stakeholder_ids = body.audience_stakeholder_ids if body.access == "NAMED_AUDIENCE" else []
    if body.access == "PUBLIC":
        site.access_code_hash = None
    await _audit(db, identity, AuditAction.MICROSITE_ACCESS_CHANGED, site, before=before)
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.get("/microsites/{site_id}/reviews", response_model=Envelope[list[ReviewOut]])
async def list_reviews(site_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    site = await _site(db, site_id)
    rows = await db.scalars(
        select(MicrositeReview).where(MicrositeReview.microsite_id == site.id).order_by(MicrositeReview.occurred_at.desc())
    )
    return ok(list(rows.all()))


@router.post("/microsites/{site_id}/reviews", response_model=Envelope[MicrositeOut])
async def review(site_id: str, body: ReviewIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    site = await _site(db, site_id)
    if body.decision == "SUBMITTED":
        if not identity.has_permission(P.MICROSITES_WRITE):
            raise Unauthorized("You cannot submit microsites.", code="PERMISSION_DENIED", status_code=403)
        if site.status not in (M.DRAFT, M.CHANGES_REQUESTED):
            raise Conflict("Only drafts can be submitted for review.", code="INVALID_TRANSITION")
        if not site.blocks:
            raise Conflict("Add content before submitting.", code="EMPTY_MICROSITE")
        site.status, site.submitted_by = M.IN_REVIEW, identity.sub
    else:
        if not identity.has_permission(P.MICROSITES_REVIEW):
            raise Unauthorized("You cannot review microsites.", code="PERMISSION_DENIED", status_code=403)
        if site.status != M.IN_REVIEW:
            raise Conflict("Only microsites in review can be decided.", code="INVALID_TRANSITION")
        if site.submitted_by == identity.sub:
            raise Conflict("Someone other than the submitter must review this version.", code="FOUR_EYES")
        if body.decision == "CHANGES_REQUESTED" and not body.comment.strip():
            raise ValidationFailed("Say what needs to change.", field_errors={"comment": ["Required."]})
        site.status = M.APPROVED if body.decision == "APPROVED" else M.CHANGES_REQUESTED
    db.add(
        MicrositeReview(
            microsite_id=site.id,
            version=site.version,
            decision=body.decision,
            comment=body.comment,
            actor=identity.display,
            actor_id=identity.sub,
        )
    )
    await _audit(db, identity, AuditAction.MICROSITE_REVIEWED, site, summary=f"{body.decision}: {body.comment}")
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.post("/microsites/{site_id}/publish", response_model=Envelope[MicrositeOut])
async def publish(site_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_PUBLISH)):
    site = await _site(db, site_id)
    if site.status != M.APPROVED:
        raise Conflict("Only approved microsites can be published.", code="INVALID_TRANSITION")
    if not site.blocks:
        raise Conflict("Add content before publishing.", code="EMPTY_MICROSITE")
    if site.access != "PUBLIC" and site.access_code_hash is None:
        raise Conflict("Set an access code before publishing a restricted microsite.", code="ACCESS_INCOMPLETE")
    site.status, site.published_version, site.published_at = M.PUBLISHED, site.version, utcnow()
    site.published_blocks, site.published_title, site.published_tagline = list(site.blocks), site.title, site.tagline
    if site.access == "NAMED_AUDIENCE":
        await enqueue(
            db,
            target_system="S074",
            event_type="microsite.audience_invitation",
            payload={
                "template": "s091-microsite-invitation",
                "stakeholderIds": site.audience_stakeholder_ids,
                "placeholders": {"title": site.title, "slug": site.slug},
            },
            idempotency_key=f"s091-invite:{site.id}:{site.version}",
        )
    await enqueue(
        db,
        target_system="S225",
        event_type="microsite.published",
        payload={"slug": site.slug, "purpose": site.purpose, "version": site.version},
        idempotency_key=f"s091-published:{site.id}:{site.version}",
    )
    await _audit(db, identity, AuditAction.MICROSITE_PUBLISHED, site)
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.post("/microsites/{site_id}/unpublish", response_model=Envelope[MicrositeOut])
async def unpublish(site_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_PUBLISH)):
    site = await _site(db, site_id)
    if site.status != M.PUBLISHED:
        raise Conflict("This microsite is not published.", code="INVALID_TRANSITION")
    site.status = M.APPROVED
    await _audit(db, identity, AuditAction.MICROSITE_UNPUBLISHED, site)
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


@router.post("/microsites/{site_id}/archive", response_model=Envelope[MicrositeOut])
async def archive(site_id: str, body: ArchiveIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_PUBLISH)):
    site = await _site(db, site_id)
    if site.status == M.ARCHIVED:
        raise Conflict("This microsite is already archived.", code="INVALID_TRANSITION")
    site.status, site.archived_at, site.archive_ref = M.ARCHIVED, utcnow(), body.archive_ref
    await _audit(db, identity, AuditAction.MICROSITE_ARCHIVED, site, summary=f"S003 {body.archive_ref}")
    await db.commit()
    await db.refresh(site)
    return ok(serialize(site))


# ── Public viewer ──


def _cookie_name(site: Microsite) -> str:
    return f"pcrm_ms_{site.id.hex[:16]}"


def _unlock_token(site: Microsite, expires: int) -> str:
    key = get_settings().SECRET_KEY.encode()
    message = f"{site.id}|{expires}|{site.access_code_hash}".encode()
    return f"{expires}.{hmac.new(key, message, hashlib.sha256).hexdigest()}"


def _unlocked(request: Request, site: Microsite) -> bool:
    value = request.cookies.get(_cookie_name(site), "")
    expires_raw, _, _ = value.partition(".")
    if not expires_raw.isdigit() or int(expires_raw) < time.time():
        return False
    return hmac.compare_digest(value, _unlock_token(site, int(expires_raw)))


async def _published(db: AsyncSession, slug: str) -> Microsite:
    site = await db.scalar(select(Microsite).where(Microsite.slug == slug, Microsite.status == M.PUBLISHED))
    if site is None:
        raise NotFound("That microsite is not available.", code="MICROSITE_NOT_FOUND")
    return site


@router.get("/public/microsites", response_model=Envelope[list[PublicMicrositeOut]])
async def public_list(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Microsite)
        .where(Microsite.status == M.PUBLISHED, Microsite.access == "PUBLIC")
        .order_by(Microsite.published_at.desc())
    )
    return ok([serialize_public(r) for r in rows.all()])


@router.get("/public/microsites/{slug}", response_model=Envelope[PublicMicrositeOut])
async def public_get(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    site = await _published(db, slug)
    if site.access != "PUBLIC" and not _unlocked(request, site):
        raise Unauthorized("Enter the access code to view this microsite.", code="MICROSITE_LOCKED")
    return ok(serialize_public(site))


@router.post("/public/microsites/{slug}/unlock", response_model=Envelope[PublicMicrositeOut])
async def public_unlock(slug: str, body: UnlockIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    hit(f"unlock:{client_ip(request)}:{slug}", settings.MICROSITE_UNLOCK_ATTEMPTS_PER_MINUTE)
    site = await _published(db, slug)
    if site.access == "PUBLIC":
        return ok(serialize_public(site))
    # Named-audience invitees may use their S081 stakeholder ID (sent to them via
    # S074) as a personal code; everyone else needs the shared access code.
    personal = site.access == "NAMED_AUDIENCE" and body.access_code.strip() in {str(x) for x in site.audience_stakeholder_ids}
    if not personal and not verify_password(body.access_code, site.access_code_hash):
        await emit_audit(
            db,
            action=AuditAction.MICROSITE_UNLOCK_FAILED,
            resource_type=ResourceType.MICROSITE,
            resource_id=site.id,
            outcome="denied",
            summary=f"from {client_ip(request)}",
        )
        await db.commit()
        raise Unauthorized("That access code is not right.", code="INVALID_ACCESS_CODE")
    expires = int(time.time()) + UNLOCK_HOURS * 3600
    response.set_cookie(
        _cookie_name(site),
        _unlock_token(site, expires),
        max_age=UNLOCK_HOURS * 3600,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return ok(serialize_public(site))


@router.post("/public/microsites/{slug}/views", status_code=204)
async def public_view(slug: str, request: Request, body: ViewIn | None = None, db: AsyncSession = Depends(get_db)):
    hit(f"view:{client_ip(request)}:{slug}", 60)
    site = await _published(db, slug)
    body = body or ViewIn()
    site.views += 1
    site.unique_visitors += int(body.new_visitor)
    site.total_seconds += body.seconds
    site.last_viewed_at = utcnow()
    await db.commit()
    return Response(status_code=204)


__all__ = ["router", "Stakeholder"]
