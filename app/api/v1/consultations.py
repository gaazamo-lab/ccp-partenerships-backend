"""
S088_consult endpoints: consultation administration and anonymous public
participation (`/public/...` needs no session but is rate limited).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit, enqueue
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, client_ip, parse_uuid, require_any_permission, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.rate_limit import hit
from app.core.rbac import P
from app.models.base import utcnow
from app.models.consultations import (
    Consultation,
    ConsultationInvitation,
    ConsultationResponse,
    ConsultationStatus,
)
from app.models.stakeholders import Segment, Stakeholder
from app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from app.schemas.consultations import (
    ConsultationCreate,
    ConsultationIn,
    ConsultationOut,
    InvitationIn,
    InvitationOut,
    OutcomeIn,
    ResponseOut,
    StatusIn,
    SubmitIn,
    SubmittedOut,
    TagIn,
    Theme,
    ThemeIn,
)
from app.services import consultations as svc
from app.services.stakeholders import resolve_members, segment_criteria

router = APIRouter(tags=["S088 Consultations"])

_READ = require_permission(P.CONSULTATIONS_READ)
_WRITE = require_permission(P.CONSULTATIONS_WRITE)
_APPROVE = require_permission(P.CONSULTATIONS_APPROVE)
_INVITE = require_permission(P.CONSULTATIONS_INVITE)
_ANALYSE = require_permission(P.CONSULTATIONS_ANALYSE)

C = ConsultationStatus


async def _one(db: AsyncSession, consultation: Consultation) -> dict:
    counts = await svc.response_counts(db, [consultation.id])
    return ok(svc.serialize(consultation, counts.get(consultation.id, 0)))


async def _unique_slug(db: AsyncSession, slug: str, except_id: uuid.UUID | None = None) -> None:
    existing = await db.scalar(select(Consultation).where(Consultation.slug == slug))
    if existing is not None and existing.id != except_id:
        raise Conflict(
            "Another consultation already uses that web address.",
            code="DUPLICATE_SLUG",
            field_errors={"slug": ["Already in use."]},
        )


def _apply(consultation: Consultation, body: ConsultationIn) -> None:
    consultation.title, consultation.slug, consultation.summary = body.title, body.slug, body.summary
    consultation.description, consultation.category = body.description, body.category
    consultation.languages = body.languages
    consultation.opens_at, consultation.closes_at = body.opens_at, body.closes_at
    consultation.estimated_minutes = body.estimated_minutes
    consultation.anonymous_allowed, consultation.collect_identity = body.anonymous_allowed, body.collect_identity
    consultation.audience_source = body.audience_source
    consultation.audience_segment_ids = body.audience_segment_ids
    consultation.questions = [q.model_dump(by_alias=True, exclude_none=True) for q in body.questions]
    consultation.triggers = [t.model_dump(by_alias=True) for t in body.triggers]


def _list_query(status_filter: str | None, search: str | None):
    query = select(Consultation)
    if status_filter:
        query = query.where(Consultation.status == status_filter)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(or_(func.lower(Consultation.title).like(term), func.lower(Consultation.summary).like(term)))
    return query


# ── Administration ──


@router.get("/consultations", response_model=PaginatedEnvelope[ConsultationOut])
async def list_consultations(
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    query = _list_query(status_filter, search)
    count = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(Consultation.opens_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    counts = await svc.response_counts(db, [r.id for r in rows])
    return paginated([svc.serialize(r, counts.get(r.id, 0)) for r in rows], count=count, page=page, page_size=page_size)


@router.get("/consultations/{consultation_id}", response_model=Envelope[ConsultationOut])
async def get_consultation(consultation_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return await _one(db, await svc.load(db, parse_uuid(consultation_id, label="consultation")))


@router.post("/consultations", response_model=Envelope[ConsultationOut], status_code=201)
async def create_consultation(body: ConsultationCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    await _unique_slug(db, body.slug)
    consultation = Consultation(
        status=C.DRAFT,
        invited_count=None if body.audience_source == "PUBLIC" else 0,
        created_by=identity.sub,
        themes=[],
    )
    if body.id:
        if await db.get(Consultation, body.id):
            raise Conflict("A consultation with this ID already exists.", code="DUPLICATE_ID")
        consultation.id = body.id
    _apply(consultation, body)
    db.add(consultation)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_CREATED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
        after={"title": body.title, "slug": body.slug},
    )
    await db.commit()
    return await _one(db, consultation)


@router.put("/consultations/{consultation_id}", response_model=Envelope[ConsultationOut])
async def update_consultation(
    consultation_id: str, body: ConsultationIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    if consultation.status not in C.EDITABLE:
        # Scheduled, open and closed consultations accept trigger changes only.
        questions = [q.model_dump(by_alias=True, exclude_none=True) for q in body.questions]
        unchanged = (
            body.title == consultation.title
            and body.slug == consultation.slug
            and body.languages == consultation.languages
            and questions == consultation.questions
        )
        if not unchanged or consultation.status == C.ARCHIVED:
            raise Conflict("Only draft or in-review consultations can be edited.", code="CONSULTATION_LOCKED")
        consultation.triggers = [t.model_dump(by_alias=True) for t in body.triggers]
        await emit_audit(
            db,
            action=AuditAction.CONSULTATION_UPDATED,
            resource_type=ResourceType.CONSULTATION,
            resource_id=consultation.id,
            identity=identity,
            summary="Triggers updated.",
        )
        await db.commit()
        return await _one(db, consultation)
    await _unique_slug(db, body.slug, except_id=consultation.id)
    _apply(consultation, body)
    if consultation.status == C.REVIEW:
        consultation.status = C.DRAFT  # changes after submission need a fresh review
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_UPDATED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
        after={"title": body.title},
    )
    await db.commit()
    return await _one(db, consultation)


@router.post("/consultations/{consultation_id}/duplicate", response_model=Envelope[ConsultationOut], status_code=201)
async def duplicate_consultation(consultation_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    source = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    slug = f"{source.slug}-copy"
    suffix = 2
    while await db.scalar(select(Consultation.id).where(Consultation.slug == slug)):
        slug, suffix = f"{source.slug}-copy-{suffix}", suffix + 1
    copy = Consultation(
        slug=slug[:80],
        title=f"{source.title} (copy)"[:240],
        summary=source.summary,
        description=source.description,
        category=source.category,
        status=C.DRAFT,
        languages=list(source.languages),
        opens_at=source.opens_at,
        closes_at=source.closes_at,
        estimated_minutes=source.estimated_minutes,
        anonymous_allowed=source.anonymous_allowed,
        collect_identity=source.collect_identity,
        audience_source=source.audience_source,
        audience_segment_ids=list(source.audience_segment_ids),
        invited_count=None if source.audience_source == "PUBLIC" else 0,
        questions=list(source.questions),
        triggers=list(source.triggers),
        themes=[],
        created_by=identity.sub,
    )
    db.add(copy)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_CREATED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=copy.id,
        identity=identity,
        summary=f"Duplicated from {source.slug}.",
    )
    await db.commit()
    return await _one(db, copy)


@router.post("/consultations/{consultation_id}/status", response_model=Envelope[ConsultationOut])
async def change_status(
    consultation_id: str,
    body: StatusIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_any_permission(P.CONSULTATIONS_WRITE, P.CONSULTATIONS_APPROVE)),
):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    target, current = body.status, consultation.status
    if current != C.REVIEW and not identity.has_permission(P.CONSULTATIONS_WRITE):
        raise Forbidden("You can only decide on consultations in review.", code="PERMISSION_DENIED")
    if target not in svc.ALLOWED_TRANSITIONS.get(current, set()):
        raise Conflict(f"A consultation cannot move from {current} to {target}.", code="INVALID_TRANSITION")
    if current == C.REVIEW and not identity.has_permission(P.CONSULTATIONS_APPROVE):
        raise Conflict("Only an approver can decide on a consultation in review.", code="APPROVER_REQUIRED")
    if current == C.REVIEW and target == C.DRAFT and not (body.comment or "").strip():
        raise ValidationFailed("Say what needs to change.", field_errors={"comment": ["Required when returning to draft."]})
    if target == C.SCHEDULED:
        if consultation.created_by == identity.sub:
            raise Conflict("Someone other than the author must approve this consultation.", code="FOUR_EYES")
        consultation.approved_by = identity.display
    if target == C.OPEN and body.closes_at is not None:
        consultation.closes_at = body.closes_at
    if target == C.OPEN and svc._aware(consultation.closes_at) <= svc.now():
        raise ValidationFailed(
            "Set a closing date in the future to open or reopen.", field_errors={"closesAt": ["Must be in the future."]}
        )
    consultation.status = target
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_STATUS_CHANGED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
        before={"status": current},
        after={"status": target, "closesAt": consultation.closes_at},
        summary=body.comment or "",
    )
    await db.commit()
    return await _one(db, consultation)


@router.put("/consultations/{consultation_id}/outcome", response_model=Envelope[ConsultationOut])
async def publish_outcome(
    consultation_id: str, body: OutcomeIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_APPROVE)
):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    if consultation.status not in (C.CLOSED, C.ARCHIVED):
        raise Conflict("Publish what you heard after the consultation closes.", code="CONSULTATION_OPEN")
    consultation.outcome_summary = body.outcome_summary
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_OUTCOME_PUBLISHED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
    )
    await db.commit()
    return await _one(db, consultation)


@router.get("/consultations/{consultation_id}/responses", response_model=Envelope[list[ResponseOut]])
async def list_responses(consultation_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_ANALYSE)):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    rows = await db.scalars(
        select(ConsultationResponse)
        .where(ConsultationResponse.consultation_id == consultation.id)
        .order_by(ConsultationResponse.submitted_at.desc())
    )
    return ok(list(rows.all()))


@router.get("/consultations/{consultation_id}/invitations", response_model=Envelope[list[InvitationOut]])
async def list_invitations(consultation_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    rows = await db.scalars(
        select(ConsultationInvitation)
        .where(ConsultationInvitation.consultation_id == consultation.id)
        .order_by(ConsultationInvitation.sent_at.desc())
    )
    return ok(list(rows.all()))


@router.post("/consultations/{consultation_id}/invitations", response_model=Envelope[InvitationOut], status_code=201)
async def send_invitations(
    consultation_id: str, body: InvitationIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_INVITE)
):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    if consultation.status not in (C.SCHEDULED, C.OPEN):
        raise Conflict("Invite people once the consultation is scheduled or open.", code="CONSULTATION_NOT_LIVE")
    if body.kind == "REMINDER" and consultation.status != C.OPEN:
        raise Conflict("Reminders are only sent while the consultation is open.", code="CONSULTATION_NOT_OPEN")
    stakeholders = list((await db.scalars(select(Stakeholder))).all())
    recipients: dict[str, str] = {}
    excluded = 0
    for raw in body.segment_ids:
        segment = await db.get(Segment, parse_uuid(raw, label="segment"))
        if segment is None:
            raise NotFound(f"Segment {raw} does not exist in S081.")
        members, _ = resolve_members(stakeholders, segment_criteria(segment))
        for member in members:
            # Consent-based distribution only (PRD §7.15): unconsented contacts are counted, never sent.
            if member.contact.consent == "Consented":
                recipients[member.contact.email.lower()] = member.contact.name
            else:
                excluded += 1
    invitation = ConsultationInvitation(
        consultation_id=consultation.id,
        kind=body.kind,
        segment_ids=body.segment_ids,
        recipient_count=len(recipients),
        excluded_count=excluded,
        sent_by=identity.display,
    )
    db.add(invitation)
    await db.flush()
    if recipients:
        message = await enqueue(
            db,
            target_system="S074",
            event_type=f"consultation.{body.kind.lower()}",
            payload={
                "template": f"s088-{body.kind.lower()}",
                "recipients": sorted(recipients),
                "placeholders": {"title": consultation.title, "slug": consultation.slug, "closesAt": consultation.closes_at},
            },
            idempotency_key=f"s088-invite:{invitation.id}",
        )
        invitation.communication_ref = f"S074-OUTBOX-{message.id.hex[:12].upper()}"
    if body.kind == "INVITATION":
        consultation.invited_count = (consultation.invited_count or 0) + len(recipients)
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_INVITATIONS_SENT,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
        after={"kind": body.kind, "recipients": len(recipients), "excluded": excluded},
    )
    await db.commit()
    await db.refresh(invitation)
    return ok(invitation)


@router.post("/consultations/{consultation_id}/themes", response_model=Envelope[Theme], status_code=201)
async def add_theme(
    consultation_id: str, body: ThemeIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_ANALYSE)
):
    consultation = await svc.load(db, parse_uuid(consultation_id, label="consultation"))
    if any(t["label"].lower() == body.label.lower() for t in consultation.themes):
        raise Conflict("That theme is already in the codebook.", code="DUPLICATE_THEME")
    theme = {"id": f"theme-{uuid.uuid4().hex[:10]}", "label": body.label, "description": body.description}
    consultation.themes = [*consultation.themes, theme]
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_THEME_ADDED,
        resource_type=ResourceType.CONSULTATION,
        resource_id=consultation.id,
        identity=identity,
        after=theme,
    )
    await db.commit()
    return ok(theme)


@router.put("/consultation-responses/{response_id}/themes", response_model=Envelope[ResponseOut])
async def tag_response(response_id: str, body: TagIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_ANALYSE)):
    response = await db.get(ConsultationResponse, parse_uuid(response_id, label="response"))
    if response is None:
        raise NotFound("That response does not exist.")
    consultation = await svc.load(db, response.consultation_id)
    theme_ids = {t["id"] for t in consultation.themes}
    question_ids = {q["id"] for q in consultation.questions}
    if body.question_id not in question_ids:
        raise ValidationFailed("That question is not part of this consultation.")
    unknown = [t for t in body.theme_ids if t not in theme_ids]
    if unknown:
        raise ValidationFailed("Add the theme to the codebook before applying it.")
    themes = dict(response.themes or {})
    if body.theme_ids:
        themes[body.question_id] = list(dict.fromkeys(body.theme_ids))
    else:
        themes.pop(body.question_id, None)
    response.themes = themes
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_RESPONSE_CODED,
        resource_type=ResourceType.CONSULTATION_RESPONSE,
        resource_id=response.id,
        identity=identity,
        after={"questionId": body.question_id, "themes": body.theme_ids},
    )
    await db.commit()
    await db.refresh(response)
    return ok(response)


# ── Public participation ──


@router.get("/public/consultations", response_model=PaginatedEnvelope[ConsultationOut])
async def public_list(
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
):
    query = _list_query(status_filter, search).where(Consultation.status.in_(C.PUBLIC))
    count = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(Consultation.closes_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    counts = await svc.response_counts(db, [r.id for r in rows])
    return paginated([svc.serialize_public(r, counts.get(r.id, 0)) for r in rows], count=count, page=page, page_size=page_size)


@router.get("/public/consultations/{slug}", response_model=Envelope[ConsultationOut])
async def public_get(slug: str, db: AsyncSession = Depends(get_db)):
    consultation = await svc.load_public(db, slug)
    counts = await svc.response_counts(db, [consultation.id])
    return ok(svc.serialize_public(consultation, counts.get(consultation.id, 0)))


@router.post("/public/consultations/{slug}/responses", response_model=Envelope[SubmittedOut], status_code=201)
async def public_submit(slug: str, body: SubmitIn, request: Request, db: AsyncSession = Depends(get_db)):
    hit(f"submit:{client_ip(request)}", get_settings().PUBLIC_SUBMISSIONS_PER_MINUTE)
    consultation = await svc.load_public(db, slug)
    if not svc.accepting_responses(consultation):
        raise Conflict("This consultation is not accepting responses.", code="CONSULTATION_CLOSED")
    if body.language not in consultation.languages:
        raise ValidationFailed("Choose one of the consultation's languages.", field_errors={"language": ["Not offered."]})
    answers = svc.validate_answers(consultation.questions, body.answers, body.language)
    if not consultation.anonymous_allowed and (body.respondent is None or not body.consent_to_identity_link):
        raise ValidationFailed(
            "This consultation needs your name, email and consent to link them to your answers.",
            field_errors={"respondent": ["Required for this consultation."]},
        )
    keep_identity = body.consent_to_identity_link and body.respondent is not None
    response = ConsultationResponse(
        consultation_id=consultation.id,
        language=body.language,
        answers=answers,
        consent_to_identity_link=keep_identity,
        respondent=body.respondent.model_dump(by_alias=True) if keep_identity and body.respondent else None,
        themes={},
        submitted_at=utcnow(),
    )
    db.add(response)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.CONSULTATION_RESPONSE_SUBMITTED,
        resource_type=ResourceType.CONSULTATION_RESPONSE,
        resource_id=response.id,
        summary=f"Response to {consultation.slug} (identity linked: {keep_identity}).",
    )
    await db.commit()
    return ok({"id": response.id})
