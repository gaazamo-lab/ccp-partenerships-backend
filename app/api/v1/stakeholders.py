"""
S081 Stakeholder / Partner CRM endpoints.

Contact, screening, consent and engagement mutations return the whole updated
stakeholder so the 360 profile never reconciles partial state.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import emit_audit, enqueue
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, client_ip, parse_uuid, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.core.rbac import P
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.stakeholders import (
    RelationshipStatus,
    ScreeningStatus,
    Segment,
    Stakeholder,
    StakeholderContact,
    StakeholderEngagement,
)
from app.schemas.common import Envelope, ok
from app.schemas.stakeholders import (
    ConsentIn,
    ContactCreate,
    ContactIn,
    EngagementIn,
    ImportIn,
    ImportResult,
    S203ActivityOut,
    S203DecisionIn,
    S203ScreeningCaseOut,
    ScreeningDecisionIn,
    SegmentCreate,
    SegmentIn,
    SegmentMemberOut,
    SegmentOut,
    StakeholderCreate,
    StakeholderIn,
    StakeholderOut,
    StatusIn,
)
from app.services import stakeholders as svc

router = APIRouter(tags=["S081 Stakeholders"])

_READ = require_permission(P.STAKEHOLDERS_READ)
_WRITE = require_permission(P.STAKEHOLDERS_WRITE)
_ENGAGE = require_permission(P.STAKEHOLDERS_ENGAGE)
_SCREEN = require_permission(P.STAKEHOLDERS_SCREEN)
_IMPORT = require_permission(P.STAKEHOLDERS_IMPORT)
_SEGMENTS = require_permission(P.SEGMENTS_WRITE)


async def _s203_identity(
    request: Request,
    api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> Identity:
    """Authenticate the S203 service without creating a browser session."""
    expected = get_settings().S203_API_KEY
    if not expected or not api_key or not secrets.compare_digest(api_key, expected):
        raise Unauthorized("A valid S203 integration key is required.", code="S203_AUTH_REQUIRED")
    return Identity(
        sub="system:s203",
        email="",
        name="S203 Screening",
        role="Integration",
        source_ip=client_ip(request),
        correlation_id=getattr(request.state, "correlation_id", ""),
    )


def _snapshot(s: Stakeholder) -> dict:
    return {
        "name": s.name,
        "category": s.category,
        "owner": s.owner,
        "status": s.status,
        "health": s.health,
        "pipelineStage": s.pipeline_stage,
        "website": s.website,
    }


def _contact_snapshot(c: StakeholderContact) -> dict:
    return {
        "name": c.name,
        "role": c.role,
        "consent": c.consent,
        "screening": c.screening,
        "active": c.active,
    }


def _s203_case(contact: StakeholderContact) -> dict:
    stakeholder = contact.stakeholder
    return {
        "case_id": contact.id,
        "status": contact.screening,
        "submitted_at": contact.created_at,
        "updated_at": contact.updated_at,
        "stakeholder": {
            "id": stakeholder.id,
            "name": stakeholder.name,
            "category": stakeholder.category,
        },
        "subject": {
            "id": contact.id,
            "name": contact.name,
            "role": contact.role,
            "email": contact.email,
            "phone": contact.phone,
        },
        "decision": contact.screening_record,
        "decision_callback": f"/api/v1/s203/screening-cases/{contact.id}/decision",
    }


async def _load_s203_contact(db: AsyncSession, contact_id: str) -> StakeholderContact:
    row = await db.scalar(
        select(StakeholderContact)
        .options(selectinload(StakeholderContact.stakeholder))
        .where(StakeholderContact.id == parse_uuid(contact_id, label="screening case"))
    )
    if row is None or row.screening == ScreeningStatus.NOT_REQUIRED:
        raise NotFound("That S203 screening case does not exist.", code="SCREENING_CASE_NOT_FOUND")
    return row


async def _request_s203_screening(
    db: AsyncSession,
    stakeholder: Stakeholder,
    contact: StakeholderContact,
    identity: Identity,
) -> None:
    """Atomically audit and queue a screening request for delivery to S203."""
    case = _s203_case(contact)
    await enqueue(
        db,
        target_system="S203",
        event_type="s203.screening_requested",
        payload={
            "caseId": str(case["case_id"]),
            "status": case["status"],
            "submittedAt": contact.created_at.isoformat(),
            "stakeholder": {
                "id": str(stakeholder.id),
                "name": stakeholder.name,
                "category": stakeholder.category,
            },
            "subject": {
                "id": str(contact.id),
                "name": contact.name,
                "role": contact.role,
                "email": contact.email,
                "phone": contact.phone,
            },
            "decisionCallback": case["decision_callback"],
        },
        idempotency_key=f"s203-screening:{contact.id}",
    )
    await emit_audit(
        db,
        action=AuditAction.CONTACT_SCREENING_REQUESTED,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
        summary=f"Submitted {contact.name} at {stakeholder.name} to S203.",
        after={"status": contact.screening, "targetSystem": "S203"},
    )


def _validate_screening_decision(body: ScreeningDecisionIn) -> None:
    if body.outcome != ScreeningStatus.CLEARED and not body.notes.strip():
        raise ValidationFailed("Explain why screening was not cleared.", field_errors={"notes": ["Required unless cleared."]})
    if body.outcome == ScreeningStatus.REJECTED and not (body.case_ref or "").strip():
        raise ValidationFailed(
            "Record the S203 case reference for a rejection.", field_errors={"caseRef": ["Required when rejected."]}
        )


async def _apply_screening_decision(
    db: AsyncSession,
    contact: StakeholderContact,
    body: ScreeningDecisionIn,
    identity: Identity,
    *,
    action: str = AuditAction.CONTACT_SCREENED,
    external_event_id: str | None = None,
) -> None:
    _validate_screening_decision(body)
    stakeholder = await svc.load_stakeholder(db, contact.stakeholder_id)
    before = contact.screening
    contact.screening = body.outcome
    contact.screening_record = {
        "outcome": body.outcome,
        "reviewer": identity.display,
        "reviewedAt": utcnow().isoformat(),
        "notes": body.notes,
        "caseRef": body.case_ref,
    }
    stakeholder.status = svc.derive_status(stakeholder)
    after = {"screening": body.outcome, "caseRef": body.case_ref}
    if external_event_id:
        after["externalEventId"] = external_event_id
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
        before={"screening": before},
        after=after,
        summary=body.notes,
    )


async def _respond(db: AsyncSession, stakeholder_id) -> dict:
    return ok(svc.serialize_stakeholder(await svc.load_stakeholder(db, stakeholder_id)))


def _apply(stakeholder: Stakeholder, body: StakeholderIn) -> None:
    stakeholder.name = body.name
    stakeholder.short_name = body.short_name or svc.make_short_name(body.name)
    stakeholder.category = body.category
    stakeholder.owner = body.owner
    stakeholder.location = body.location
    stakeholder.website = body.website
    stakeholder.description = body.description
    if body.health:
        stakeholder.health = body.health
    if body.pipeline_stage:
        stakeholder.pipeline_stage = body.pipeline_stage


# ── Stakeholders ──


@router.get("/stakeholders", response_model=Envelope[list[StakeholderOut]], summary="Stakeholder register")
async def list_stakeholders(
    search: str | None = None,
    category: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    owner: str | None = None,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    query = select(Stakeholder).order_by(Stakeholder.name)
    if category:
        query = query.where(Stakeholder.category == category)
    if status_filter:
        query = query.where(Stakeholder.status == status_filter)
    if owner:
        query = query.where(Stakeholder.owner == owner)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(func.lower(Stakeholder.name).like(term) | func.lower(Stakeholder.short_name).like(term))
    rows = (await db.scalars(query)).all()
    return ok([svc.serialize_stakeholder(row) for row in rows])


@router.get("/stakeholders/{stakeholder_id}", response_model=Envelope[StakeholderOut])
async def get_stakeholder(stakeholder_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return await _respond(db, parse_uuid(stakeholder_id, label="stakeholder"))


@router.post("/stakeholders", response_model=Envelope[StakeholderOut], status_code=status.HTTP_201_CREATED)
async def create_stakeholder(body: StakeholderCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    svc.reject_individual_records(body.website)
    if body.id and await db.get(Stakeholder, body.id):
        raise Conflict("A stakeholder with this ID already exists.", code="DUPLICATE_ID")
    duplicate = await svc.find_duplicate(db, name=body.name, website=body.website)
    if duplicate is not None:
        if not body.force:
            raise Conflict(
                f"{duplicate.name} already exists in the register.",
                code="DUPLICATE_STAKEHOLDER",
                extra={"duplicateId": str(duplicate.id), "duplicateName": duplicate.name},
            )
        if not (body.override_reason or "").strip():
            raise ValidationFailed(
                "Give a reason for creating a possible duplicate.",
                field_errors={"overrideReason": ["Required when creating a possible duplicate."]},
            )
    stakeholder = Stakeholder(
        status=RelationshipStatus.SCREENING_PENDING if svc.is_regulated(body.category) else RelationshipStatus.ACTIVE,
        created_by=identity.sub,
        duplicate_override_reason=body.override_reason if duplicate else None,
    )
    if body.id:
        stakeholder.id = body.id
    _apply(stakeholder, body)
    db.add(stakeholder)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.STAKEHOLDER_CREATED,
        resource_type=ResourceType.STAKEHOLDER,
        resource_id=stakeholder.id,
        identity=identity,
        after=_snapshot(stakeholder),
        summary=f"Created despite duplicate: {body.override_reason}" if duplicate else "",
    )
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.put("/stakeholders/{stakeholder_id}", response_model=Envelope[StakeholderOut])
async def update_stakeholder(
    stakeholder_id: str, body: StakeholderIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    stakeholder = await svc.load_stakeholder(db, parse_uuid(stakeholder_id, label="stakeholder"))
    svc.reject_individual_records(body.website)
    duplicate = await svc.find_duplicate(db, name=body.name, website=body.website, except_id=stakeholder.id)
    if duplicate is not None:
        raise Conflict(
            f"{duplicate.name} already uses that name or website.",
            code="DUPLICATE_STAKEHOLDER",
            extra={"duplicateId": str(duplicate.id), "duplicateName": duplicate.name},
        )
    before = _snapshot(stakeholder)
    _apply(stakeholder, body)
    await emit_audit(
        db,
        action=AuditAction.STAKEHOLDER_UPDATED,
        resource_type=ResourceType.STAKEHOLDER,
        resource_id=stakeholder.id,
        identity=identity,
        before=before,
        after=_snapshot(stakeholder),
    )
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.post("/stakeholders/{stakeholder_id}/status", response_model=Envelope[StakeholderOut])
async def set_status(
    stakeholder_id: str, body: StatusIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    stakeholder = await svc.load_stakeholder(db, parse_uuid(stakeholder_id, label="stakeholder"))
    before = stakeholder.status
    if body.status == RelationshipStatus.SCREENING_PENDING:
        raise ValidationFailed("Screening pending is set automatically from contact screening.")
    if body.status != RelationshipStatus.INACTIVE and svc.has_blocking_screening(stakeholder):
        stakeholder.status = RelationshipStatus.SCREENING_PENDING
    else:
        stakeholder.status = body.status
    await emit_audit(
        db,
        action=AuditAction.STAKEHOLDER_STATUS_CHANGED,
        resource_type=ResourceType.STAKEHOLDER,
        resource_id=stakeholder.id,
        identity=identity,
        before={"status": before},
        after={"status": stakeholder.status},
    )
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.post("/stakeholders/imports", response_model=Envelope[ImportResult], summary="Spreadsheet import")
async def import_stakeholders(body: ImportIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_IMPORT)):
    existing = (await db.scalars(select(Stakeholder))).all()
    names = {svc.normalized(s.name) for s in existing}
    sites = {svc.normalized_site(s.website) for s in existing if s.website}
    skipped: list[dict] = []
    created = duplicates = 0
    for index, row in enumerate(body.rows, start=1):
        name, site = svc.normalized(row.name), svc.normalized_site(row.website)
        if name in names or (site and site in sites):
            duplicates += 1
            skipped.append({"row": index, "name": row.name, "reason": "Matches an existing stakeholder."})
            continue
        try:
            svc.reject_individual_records(row.website)
        except ValidationFailed as exc:
            skipped.append({"row": index, "name": row.name, "reason": exc.message})
            continue
        stakeholder = Stakeholder(
            status=RelationshipStatus.SCREENING_PENDING if svc.is_regulated(row.category) else RelationshipStatus.ACTIVE,
            created_by=identity.sub,
        )
        _apply(stakeholder, row)
        db.add(stakeholder)
        names.add(name)
        if site:
            sites.add(site)
        created += 1
    await emit_audit(
        db,
        action=AuditAction.STAKEHOLDERS_IMPORTED,
        resource_type=ResourceType.STAKEHOLDER,
        identity=identity,
        summary=f"Import: {created} created, {duplicates} duplicates, {len(skipped) - duplicates} rejected.",
        after={"created": created, "duplicates": duplicates, "rows": len(body.rows)},
    )
    await db.commit()
    return ok({"created": created, "duplicates": duplicates, "skipped": skipped})


# ── S203 screening integration ──


@router.get(
    "/s203/screening-cases",
    response_model=Envelope[list[S203ScreeningCaseOut]],
    summary="S203 screening work queue",
)
async def list_s203_screening_cases(
    screening_status: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _identity: Identity = Depends(_s203_identity),
):
    if screening_status is not None and screening_status not in ScreeningStatus.ALL:
        raise ValidationFailed(
            "Unknown screening status.",
            field_errors={"status": [f"Use one of: {', '.join(ScreeningStatus.ALL)}."]},
        )
    query = (
        select(StakeholderContact)
        .options(selectinload(StakeholderContact.stakeholder))
        .where(StakeholderContact.screening != ScreeningStatus.NOT_REQUIRED)
    )
    if screening_status is not None:
        query = query.where(StakeholderContact.screening == screening_status)
    contacts = (await db.scalars(query.order_by(StakeholderContact.created_at))).all()
    return ok([_s203_case(contact) for contact in contacts])


@router.get(
    "/s203/screening-cases/{contact_id}/activities",
    response_model=Envelope[list[S203ActivityOut]],
    summary="S203 screening activity history",
)
async def list_s203_screening_activities(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    _identity: Identity = Depends(_s203_identity),
):
    contact = await _load_s203_contact(db, contact_id)
    actions = [
        AuditAction.CONTACT_SCREENING_REQUESTED,
        AuditAction.CONTACT_SCREENED,
        AuditAction.S203_SCREENING_DECISION_RECEIVED,
    ]
    rows = (
        await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == ResourceType.CONTACT,
                AuditEvent.resource_id == str(contact.id),
                AuditEvent.action.in_(actions),
            )
            .order_by(AuditEvent.sequence)
        )
    ).all()
    return ok(
        [
            {
                "id": row.id,
                "occurred_at": row.occurred_at,
                "action": row.action,
                "actor": row.actor_email or row.actor_id,
                "summary": row.summary,
                "before": row.before,
                "after": row.after,
            }
            for row in rows
        ]
    )


@router.post(
    "/s203/screening-cases/{contact_id}/decision",
    response_model=Envelope[S203ScreeningCaseOut],
    summary="Receive an S203 screening decision",
)
async def receive_s203_screening_decision(
    contact_id: str,
    body: S203DecisionIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_s203_identity),
):
    contact = await _load_s203_contact(db, contact_id)
    prior_events = (
        await db.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type == ResourceType.CONTACT,
                AuditEvent.resource_id == str(contact.id),
                AuditEvent.action == AuditAction.S203_SCREENING_DECISION_RECEIVED,
            )
        )
    ).all()
    if not any((event.after or {}).get("externalEventId") == body.event_id for event in prior_events):
        await _apply_screening_decision(
            db,
            contact,
            body,
            identity,
            action=AuditAction.S203_SCREENING_DECISION_RECEIVED,
            external_event_id=body.event_id,
        )
        await db.commit()
    refreshed = await _load_s203_contact(db, contact_id)
    return ok(_s203_case(refreshed))


# ── Contacts ──


async def _contact_rules(db: AsyncSession, stakeholder: Stakeholder, body: ContactIn, except_id=None) -> None:
    if await svc.email_in_use(db, body.email, except_id=except_id):
        raise Conflict(f"A contact with {body.email} already exists.", code="DUPLICATE_CONTACT")
    for contact in stakeholder.contacts:
        if contact.id != except_id and contact.active and svc.normalized(contact.name) == svc.normalized(body.name):
            raise Conflict(f"{body.name} is already a contact for {stakeholder.name}.", code="DUPLICATE_CONTACT")


@router.post("/stakeholders/{stakeholder_id}/contacts", response_model=Envelope[StakeholderOut], status_code=201)
async def add_contact(
    stakeholder_id: str, body: ContactCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    stakeholder = await svc.load_stakeholder(db, parse_uuid(stakeholder_id, label="stakeholder"))
    await _contact_rules(db, stakeholder, body)
    regulated = body.regulated or svc.is_regulated(stakeholder.category)
    contact = StakeholderContact(
        stakeholder_id=stakeholder.id,
        name=body.name,
        role=body.role,
        email=body.email.lower(),
        phone=body.phone,
        consent=body.consent,
        consent_date=body.consent_date,
        consent_channel=body.consent_channel,
        screening=ScreeningStatus.PENDING if regulated else ScreeningStatus.NOT_REQUIRED,
    )
    if body.id:
        contact.id = body.id
    stakeholder.contacts.append(contact)
    await db.flush()
    stakeholder.status = svc.derive_status(stakeholder)
    await emit_audit(
        db,
        action=AuditAction.CONTACT_CREATED,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
        after=_contact_snapshot(contact),
    )
    if contact.screening == ScreeningStatus.PENDING:
        await _request_s203_screening(db, stakeholder, contact, identity)
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.put("/stakeholder-contacts/{contact_id}", response_model=Envelope[StakeholderOut])
async def update_contact(
    contact_id: str, body: ContactIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    contact = await svc.load_contact(db, parse_uuid(contact_id, label="contact"))
    stakeholder = await svc.load_stakeholder(db, contact.stakeholder_id)
    await _contact_rules(db, stakeholder, body, except_id=contact.id)
    before = _contact_snapshot(contact)
    screening_before = contact.screening
    contact.name, contact.role, contact.email, contact.phone = body.name, body.role, body.email.lower(), body.phone
    contact.consent, contact.consent_date, contact.consent_channel = body.consent, body.consent_date, body.consent_channel
    if body.regulated and contact.screening == ScreeningStatus.NOT_REQUIRED:
        contact.screening = ScreeningStatus.PENDING
    if body.active is not None:
        contact.active = body.active
    stakeholder.status = svc.derive_status(stakeholder)
    await emit_audit(
        db,
        action=AuditAction.CONTACT_UPDATED,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
        before=before,
        after=_contact_snapshot(contact),
    )
    if screening_before == ScreeningStatus.NOT_REQUIRED and contact.screening == ScreeningStatus.PENDING:
        await _request_s203_screening(db, stakeholder, contact, identity)
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.post("/stakeholder-contacts/{contact_id}/deactivate", response_model=Envelope[StakeholderOut])
async def deactivate_contact(contact_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    contact = await svc.load_contact(db, parse_uuid(contact_id, label="contact"))
    stakeholder = await svc.load_stakeholder(db, contact.stakeholder_id)
    contact.active = False
    stakeholder.status = svc.derive_status(stakeholder)
    await emit_audit(
        db,
        action=AuditAction.CONTACT_DEACTIVATED,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
    )
    await db.commit()
    return await _respond(db, stakeholder.id)


@router.post("/stakeholder-contacts/{contact_id}/screening", response_model=Envelope[StakeholderOut])
async def record_screening(
    contact_id: str, body: ScreeningDecisionIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_SCREEN)
):
    contact = await svc.load_contact(db, parse_uuid(contact_id, label="contact"))
    await _apply_screening_decision(db, contact, body, identity)
    await db.commit()
    return await _respond(db, contact.stakeholder_id)


@router.put("/stakeholder-contacts/{contact_id}/consent", response_model=Envelope[StakeholderOut])
async def record_consent(
    contact_id: str, body: ConsentIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    contact = await svc.load_contact(db, parse_uuid(contact_id, label="contact"))
    if body.consent in {"Consented", "Withdrawn"} and (body.consent_date is None or body.consent_channel is None):
        raise ValidationFailed(
            "Record when and how consent was given or withdrawn.",
            field_errors={
                "consentDate": ["Required when consent is given or withdrawn."],
                "consentChannel": ["Required when consent is given or withdrawn."],
            },
        )
    if body.consent_date is not None and body.consent_date > dt.date.today():
        raise ValidationFailed(
            "Consent dates cannot be in the future.", field_errors={"consentDate": ["Cannot be in the future."]}
        )
    before = {
        "consent": contact.consent,
        "date": contact.consent_date,
        "channel": contact.consent_channel,
    }
    contact.consent, contact.consent_date, contact.consent_channel = body.consent, body.consent_date, body.consent_channel
    await emit_audit(
        db,
        action=AuditAction.CONTACT_CONSENT_RECORDED,
        resource_type=ResourceType.CONTACT,
        resource_id=contact.id,
        identity=identity,
        before=before,
        after={"consent": body.consent, "date": body.consent_date, "channel": body.consent_channel},
    )
    await db.commit()
    return await _respond(db, contact.stakeholder_id)


# ── Engagements ──


@router.post("/stakeholders/{stakeholder_id}/engagements", response_model=Envelope[StakeholderOut], status_code=201)
async def add_engagement(
    stakeholder_id: str, body: EngagementIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_ENGAGE)
):
    stakeholder = await svc.load_stakeholder(db, parse_uuid(stakeholder_id, label="stakeholder"))
    if svc.has_blocking_screening(stakeholder):
        raise Conflict("This stakeholder cannot be engaged until S203 screening is complete.", code="SCREENING_REQUIRED")
    if stakeholder.status == RelationshipStatus.INACTIVE:
        raise Conflict("Reactivate this stakeholder before logging engagement.", code="STAKEHOLDER_INACTIVE")
    when = body.date or dt.date.today()
    if when > dt.date.today():
        raise ValidationFailed("Engagements are logged after they happen.", field_errors={"date": ["Cannot be in the future."]})
    engagement = StakeholderEngagement(
        stakeholder_id=stakeholder.id,
        type=body.type,
        title=body.title,
        summary=body.summary,
        date=when,
        source="Partner CRM",
        logged_by=identity.sub,
    )
    if body.id:
        engagement.id = body.id
    stakeholder.engagements.append(engagement)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.ENGAGEMENT_LOGGED,
        resource_type=ResourceType.STAKEHOLDER,
        resource_id=stakeholder.id,
        identity=identity,
        after={"type": body.type, "title": body.title, "date": when.isoformat()},
    )
    await db.commit()
    return await _respond(db, stakeholder.id)


# ── Segments ──


async def _all_stakeholders(db: AsyncSession) -> list[Stakeholder]:
    return list((await db.scalars(select(Stakeholder))).all())


async def _get_segment(db: AsyncSession, segment_id: str) -> Segment:
    segment = await db.get(Segment, parse_uuid(segment_id, label="segment"))
    if segment is None:
        raise NotFound("That segment does not exist.")
    return segment


def _criteria_dict(body: SegmentIn) -> dict:
    criteria = body.criteria
    return {
        "categories": criteria.categories if criteria else body.categories,
        "statuses": criteria.statuses if criteria else [],
        "owners": criteria.owners if criteria else [],
        "consentedOnly": criteria.consented_only if criteria else False,
    }


async def _unique_segment_name(db: AsyncSession, name: str, except_id=None) -> None:
    query = select(Segment).where(func.lower(Segment.name) == name.strip().lower())
    existing = await db.scalar(query)
    if existing is not None and existing.id != except_id:
        raise Conflict("A segment with that name already exists.", code="DUPLICATE_SEGMENT")


@router.get("/segments", response_model=Envelope[list[SegmentOut]], summary="Live audience segments")
async def list_segments(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    stakeholders = await _all_stakeholders(db)
    segments = (await db.scalars(select(Segment).order_by(Segment.name))).all()
    return ok([svc.serialize_segment(segment, stakeholders) for segment in segments])


@router.post("/segments", response_model=Envelope[SegmentOut], status_code=201)
async def create_segment(body: SegmentCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_SEGMENTS)):
    await _unique_segment_name(db, body.name)
    segment = Segment(name=body.name, description=body.description, criteria=_criteria_dict(body), used_by=body.used_by)
    if body.id:
        segment.id = body.id
    db.add(segment)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.SEGMENT_CREATED,
        resource_type=ResourceType.SEGMENT,
        resource_id=segment.id,
        identity=identity,
        after={"name": segment.name, "criteria": segment.criteria},
    )
    await db.commit()
    return ok(svc.serialize_segment(segment, await _all_stakeholders(db)))


@router.put("/segments/{segment_id}", response_model=Envelope[SegmentOut])
async def update_segment(
    segment_id: str, body: SegmentIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_SEGMENTS)
):
    segment = await _get_segment(db, segment_id)
    await _unique_segment_name(db, body.name, except_id=segment.id)
    before = {"name": segment.name, "criteria": segment.criteria}
    segment.name, segment.description = body.name, body.description
    segment.criteria, segment.used_by = _criteria_dict(body), body.used_by
    segment.updated_at = utcnow()
    await emit_audit(
        db,
        action=AuditAction.SEGMENT_UPDATED,
        resource_type=ResourceType.SEGMENT,
        resource_id=segment.id,
        identity=identity,
        before=before,
        after={"name": segment.name, "criteria": segment.criteria},
    )
    await db.commit()
    return ok(svc.serialize_segment(segment, await _all_stakeholders(db)))


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_segment(segment_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_SEGMENTS)):
    segment = await _get_segment(db, segment_id)
    await emit_audit(
        db,
        action=AuditAction.SEGMENT_DELETED,
        resource_type=ResourceType.SEGMENT,
        resource_id=segment.id,
        identity=identity,
        before={"name": segment.name, "criteria": segment.criteria},
    )
    await db.delete(segment)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/segments/{segment_id}/members", response_model=Envelope[list[SegmentMemberOut]])
async def segment_members(segment_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    segment = await _get_segment(db, segment_id)
    members, _ = svc.resolve_members(await _all_stakeholders(db), svc.segment_criteria(segment))
    return ok(
        [
            {
                "stakeholder_id": m.stakeholder.id,
                "stakeholder_name": m.stakeholder.name,
                "contact_id": m.contact.id,
                "contact_name": m.contact.name,
                "email": m.contact.email,
                "consent": m.contact.consent,
            }
            for m in members
        ]
    )
