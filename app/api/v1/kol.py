"""
S092 KOL & Thought-Leader Tracker endpoints. Stage rules follow
partner-crm `docs/architecture/new-module-rules.md` (S092).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, parse_uuid, require_permission
from app.core.database import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.rbac import P
from app.models.base import utcnow
from app.models.kol import KolContent, KolEngagement, KolMediaMention, KolProfile
from app.models.stakeholders import Stakeholder
from app.schemas.common import Envelope, ok
from app.schemas.kol import (
    ContentIn,
    ContentOut,
    ContentStageIn,
    EngagementIn,
    EngagementOut,
    EngagementStageIn,
    KolIn,
    KolOut,
    MentionIn,
    MentionOut,
    ParticipationIn,
)

router = APIRouter(tags=["S092 KOL tracker"])

_READ = require_permission(P.KOL_READ)
_WRITE = require_permission(P.KOL_WRITE)

ENGAGEMENT_TRANSITIONS: dict[str, set[str]] = {
    "PLANNED": {"INVITED", "CANCELLED"},
    "INVITED": {"CONFIRMED", "DECLINED", "CANCELLED"},
    "CONFIRMED": {"COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "DECLINED": set(),
    "CANCELLED": set(),
}

CONTENT_TRANSITIONS: dict[str, set[str]] = {
    "COMMISSIONED": {"DRAFT_SUBMITTED", "WITHDRAWN"},
    "DRAFT_SUBMITTED": {"IN_REVIEW", "WITHDRAWN"},
    "IN_REVIEW": {"CHANGES_REQUESTED", "APPROVED", "WITHDRAWN"},
    "CHANGES_REQUESTED": {"DRAFT_SUBMITTED", "WITHDRAWN"},
    "APPROVED": {"PUBLISHED", "WITHDRAWN"},
    "PUBLISHED": set(),
    "WITHDRAWN": set(),
}


async def _profile(db: AsyncSession, kol_id: str) -> KolProfile:
    row = await db.get(KolProfile, parse_uuid(kol_id, label="KOL"))
    if row is None:
        raise NotFound("That KOL profile does not exist.", code="KOL_NOT_FOUND")
    return row


async def _validate_profile(db: AsyncSession, body: KolIn, except_id: uuid.UUID | None = None) -> uuid.UUID | None:
    stakeholder_id = None
    if body.stakeholder_id:
        stakeholder_id = parse_uuid(body.stakeholder_id, label="stakeholder")
        if await db.get(Stakeholder, stakeholder_id) is None:
            raise ValidationFailed(
                "Link the KOL to an existing S081 stakeholder.", field_errors={"stakeholderId": ["Not found in S081."]}
            )
    if body.email:
        clash = await db.scalar(select(KolProfile).where(func.lower(KolProfile.email) == body.email.lower()))
        if clash is not None and clash.id != except_id:
            raise Conflict(f"{clash.full_name} already uses that email.", code="DUPLICATE_KOL")
    return stakeholder_id


def _apply(profile: KolProfile, body: KolIn, stakeholder_id: uuid.UUID | None) -> None:
    data = body.model_dump(exclude={"stakeholder_id"})
    data["email"] = (data["email"] or "").lower()
    for key, value in data.items():
        setattr(profile, key, value)
    profile.stakeholder_id = stakeholder_id


# ── Profiles ──


@router.get("/kols", response_model=Envelope[list[KolOut]])
async def list_kols(
    search: str | None = None,
    category: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    stakeholder_id: str | None = Query(None, alias="stakeholderId"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    query = select(KolProfile).order_by(KolProfile.full_name)
    if category:
        query = query.where(KolProfile.category == category)
    if status_filter:
        query = query.where(KolProfile.status == status_filter)
    if stakeholder_id:
        query = query.where(KolProfile.stakeholder_id == parse_uuid(stakeholder_id, label="stakeholder"))
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(or_(func.lower(KolProfile.full_name).like(term), func.lower(KolProfile.organisation).like(term)))
    return ok(list((await db.scalars(query)).all()))


@router.get("/kols/{kol_id}", response_model=Envelope[KolOut])
async def get_kol(kol_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return ok(await _profile(db, kol_id))


@router.post("/kols", response_model=Envelope[KolOut], status_code=201)
async def create_kol(body: KolIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    profile = KolProfile()
    _apply(profile, body, await _validate_profile(db, body))
    db.add(profile)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.KOL_CREATED,
        resource_type=ResourceType.KOL,
        resource_id=profile.id,
        identity=identity,
        after={"fullName": body.full_name, "category": body.category},
    )
    await db.commit()
    await db.refresh(profile)
    return ok(profile)


@router.put("/kols/{kol_id}", response_model=Envelope[KolOut])
async def update_kol(kol_id: str, body: KolIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    profile = await _profile(db, kol_id)
    before = {"status": profile.status, "riskLevel": profile.risk_level}
    _apply(profile, body, await _validate_profile(db, body, except_id=profile.id))
    await emit_audit(
        db,
        action=AuditAction.KOL_UPDATED,
        resource_type=ResourceType.KOL,
        resource_id=profile.id,
        identity=identity,
        before=before,
        after={"status": body.status, "riskLevel": body.risk_level},
    )
    await db.commit()
    await db.refresh(profile)
    return ok(profile)


# ── Engagements ──


async def _engagement(db: AsyncSession, engagement_id: str) -> KolEngagement:
    row = await db.get(KolEngagement, parse_uuid(engagement_id, label="engagement"))
    if row is None:
        raise NotFound("That engagement does not exist.")
    return row


@router.get("/kol-engagements", response_model=Envelope[list[EngagementOut]])
async def list_engagements(
    kol_id: str | None = Query(None, alias="kolId"), db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)
):
    query = select(KolEngagement).order_by(KolEngagement.scheduled_for.desc(), KolEngagement.created_at.desc())
    if kol_id:
        query = query.where(KolEngagement.kol_id == parse_uuid(kol_id, label="KOL"))
    return ok(list((await db.scalars(query)).all()))


@router.post("/kols/{kol_id}/engagements", response_model=Envelope[EngagementOut], status_code=201)
async def create_engagement(
    kol_id: str, body: EngagementIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    profile = await _profile(db, kol_id)
    if profile.status == "ARCHIVED":
        raise Conflict("Archived KOLs cannot be engaged.", code="KOL_ARCHIVED")
    engagement = KolEngagement(kol_id=profile.id, stage="PLANNED", **body.model_dump())
    db.add(engagement)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.KOL_ENGAGEMENT_CREATED,
        resource_type=ResourceType.KOL_ENGAGEMENT,
        resource_id=engagement.id,
        identity=identity,
        after={"type": body.type, "title": body.title},
    )
    await db.commit()
    await db.refresh(engagement)
    return ok(engagement)


@router.post("/kol-engagements/{engagement_id}/stage", response_model=Envelope[EngagementOut])
async def move_engagement(
    engagement_id: str, body: EngagementStageIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    if body.stage not in ENGAGEMENT_TRANSITIONS[engagement.stage]:
        raise Conflict(f"An engagement cannot move from {engagement.stage} to {body.stage}.", code="INVALID_TRANSITION")
    before = engagement.stage
    engagement.stage = body.stage
    if body.note.strip():
        engagement.notes = f"{engagement.notes}\n{body.note}".strip()
    await emit_audit(
        db,
        action=AuditAction.KOL_ENGAGEMENT_MOVED,
        resource_type=ResourceType.KOL_ENGAGEMENT,
        resource_id=engagement.id,
        identity=identity,
        before={"stage": before},
        after={"stage": body.stage},
    )
    await db.commit()
    await db.refresh(engagement)
    return ok(engagement)


@router.put("/kol-engagements/{engagement_id}/participation", response_model=Envelope[EngagementOut])
async def record_participation(
    engagement_id: str, body: ParticipationIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    if engagement.stage not in ("CONFIRMED", "COMPLETED"):
        raise Conflict("Record participation once the engagement is confirmed or completed.", code="INVALID_TRANSITION")
    engagement.stage = "COMPLETED"
    engagement.participation = {
        **body.model_dump(by_alias=True),
        "recordedAt": utcnow().isoformat(),
        "recordedBy": identity.display,
    }
    # A completed engagement makes a prospect an active KOL.
    profile = await db.get(KolProfile, engagement.kol_id)
    if profile is not None and profile.status == "PROSPECT":
        profile.status = "ACTIVE"
    await emit_audit(
        db,
        action=AuditAction.KOL_PARTICIPATION_RECORDED,
        resource_type=ResourceType.KOL_ENGAGEMENT,
        resource_id=engagement.id,
        identity=identity,
        after={"attended": body.attended, "score": body.contribution_score},
    )
    await db.commit()
    await db.refresh(engagement)
    return ok(engagement)


# ── Content collaborations ──


@router.get("/kol-content", response_model=Envelope[list[ContentOut]])
async def list_content(
    kol_id: str | None = Query(None, alias="kolId"), db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)
):
    query = select(KolContent).order_by(KolContent.updated_at.desc())
    if kol_id:
        query = query.where(KolContent.kol_id == parse_uuid(kol_id, label="KOL"))
    return ok(list((await db.scalars(query)).all()))


@router.post("/kols/{kol_id}/content", response_model=Envelope[ContentOut], status_code=201)
async def create_content(kol_id: str, body: ContentIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    profile = await _profile(db, kol_id)
    if profile.status == "ARCHIVED":
        raise Conflict("Archived KOLs cannot be commissioned.", code="KOL_ARCHIVED")
    content = KolContent(kol_id=profile.id, stage="COMMISSIONED", **body.model_dump())
    db.add(content)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.KOL_CONTENT_CREATED,
        resource_type=ResourceType.KOL_CONTENT,
        resource_id=content.id,
        identity=identity,
        after={"title": body.title},
    )
    await db.commit()
    await db.refresh(content)
    return ok(content)


@router.post("/kol-content/{content_id}/stage", response_model=Envelope[ContentOut])
async def move_content(
    content_id: str, body: ContentStageIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    content = await db.get(KolContent, parse_uuid(content_id, label="content"))
    if content is None:
        raise NotFound("That content item does not exist.")
    if body.stage not in CONTENT_TRANSITIONS[content.stage]:
        raise Conflict(f"Content cannot move from {content.stage} to {body.stage}.", code="INVALID_TRANSITION")
    if body.stage == "DRAFT_SUBMITTED":
        if not (body.draft_ref or content.draft_ref):
            raise ValidationFailed("Attach the S003 draft reference.", field_errors={"draftRef": ["Required."]})
        content.draft_ref = body.draft_ref or content.draft_ref
    if body.stage == "CHANGES_REQUESTED":
        if not (body.review_notes or "").strip():
            raise ValidationFailed("Say what needs to change.", field_errors={"reviewNotes": ["Required."]})
    if body.stage in ("IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"):
        content.reviewer = identity.display
    if body.review_notes is not None:
        content.review_notes = body.review_notes
    if body.stage == "PUBLISHED":
        if not body.published_url:
            raise ValidationFailed("Add the published link.", field_errors={"publishedUrl": ["Required."]})
        content.published_url, content.cms_ref, content.published_at = body.published_url, body.cms_ref, utcnow()
    before = content.stage
    content.stage = body.stage
    await emit_audit(
        db,
        action=AuditAction.KOL_CONTENT_MOVED,
        resource_type=ResourceType.KOL_CONTENT,
        resource_id=content.id,
        identity=identity,
        before={"stage": before},
        after={"stage": body.stage},
    )
    await db.commit()
    await db.refresh(content)
    return ok(content)


# ── Media reach ──


@router.get("/kol-mentions", response_model=Envelope[list[MentionOut]])
async def list_mentions(
    kol_id: str | None = Query(None, alias="kolId"), db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)
):
    query = select(KolMediaMention).order_by(KolMediaMention.published_at.desc())
    if kol_id:
        query = query.where(KolMediaMention.kol_id == parse_uuid(kol_id, label="KOL"))
    return ok(list((await db.scalars(query)).all()))


@router.post("/kols/{kol_id}/mentions", response_model=Envelope[MentionOut], status_code=201)
async def add_mention(kol_id: str, body: MentionIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    profile = await _profile(db, kol_id)
    content_id = None
    if body.content_id:
        content_id = parse_uuid(body.content_id, label="content")
        content = await db.get(KolContent, content_id)
        if content is None or content.kol_id != profile.id:
            raise ValidationFailed(
                "Attribute the mention to this KOL's own content.", field_errors={"contentId": ["Not this KOL's content."]}
            )
    mention = KolMediaMention(
        kol_id=profile.id, content_id=content_id, source="MANUAL", **body.model_dump(exclude={"content_id"})
    )
    db.add(mention)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.KOL_MENTION_ADDED,
        resource_type=ResourceType.KOL,
        resource_id=profile.id,
        identity=identity,
        after={"outlet": body.outlet, "reach": body.reach},
    )
    await db.commit()
    await db.refresh(mention)
    return ok(mention)
