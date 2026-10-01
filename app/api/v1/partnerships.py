"""
S082 MOU & Partnership Lifecycle Tracker endpoints
(contract: partner-crm `docs/architecture/s082-backend-contract.md`).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit, enqueue
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, parse_uuid, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.rbac import P
from app.models.audit import OutboxEvent, OutboxStatus
from app.models.base import utcnow
from app.models.partnerships import (
    ObligationProgressNote,
    ObligationStatus,
    PartnershipAgreement,
    PartnershipHistory,
    PartnershipObligation,
    PartnershipRenewal,
    PartnershipRenewalAlert,
    PartnershipReview,
    PartnershipStatus,
    RenewalAlertStatus,
)
from app.models.stakeholders import Stakeholder
from app.schemas.common import Envelope, PaginatedEnvelope, ok, paginated
from app.schemas.partnerships import (
    AlertsConfigIn,
    HistoryOut,
    IntegrationHealthOut,
    ObligationCreate,
    ObligationOut,
    ObligationUpdate,
    PartnershipCreate,
    PartnershipImportIn,
    PartnershipImportResult,
    PartnershipOut,
    PartnershipUpdate,
    ProgressIn,
    ProgressOut,
    RenewalAlertOut,
    RenewalOut,
    RenewIn,
    ReviewCreate,
    ReviewIn,
    ReviewOut,
    TerminateIn,
    TransitionIn,
)
from app.services import partnerships as svc

router = APIRouter(tags=["S082 Partnerships"])

_READ = require_permission(P.PARTNERSHIPS_READ)
_CREATE = require_permission(P.PARTNERSHIPS_CREATE)
_EDIT = require_permission(P.PARTNERSHIPS_EDIT)
_OBLIGATIONS = require_permission(P.PARTNERSHIPS_OBLIGATIONS)
_REVIEWS = require_permission(P.PARTNERSHIPS_REVIEWS)
_LIFECYCLE = require_permission(P.PARTNERSHIPS_LIFECYCLE)
_IMPORT = require_permission(P.PARTNERSHIPS_IMPORT)
_EXPORT = require_permission(P.PARTNERSHIPS_EXPORT)

S = PartnershipStatus


def _snapshot(a: PartnershipAgreement) -> dict:
    return {
        "reference": a.reference,
        "title": a.title,
        "status": a.status,
        "owner": a.owner,
        "effectiveDate": a.effective_date,
        "expiryDate": a.expiry_date,
        "legalContractRef": a.legal_contract_ref,
        "signedDocumentRef": a.signed_document_ref,
    }


async def _agreement(db: AsyncSession, agreement_id: str) -> PartnershipAgreement:
    return await svc.load_agreement(db, parse_uuid(agreement_id, label="agreement"))


async def _respond(db: AsyncSession, agreement_id, response: Response | None = None) -> dict:
    agreement = await svc.load_agreement(db, agreement_id)
    if response is not None:
        response.headers["ETag"] = f'"{agreement.version}"'
    return ok(svc.serialize_agreement(agreement))


async def _audit(db, identity, action, agreement, *, before=None, summary=""):
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.PARTNERSHIP,
        resource_id=agreement.id,
        identity=identity,
        before=before,
        after=_snapshot(agreement),
        summary=summary,
    )


# ── Agreements ──


@router.get("/partnerships", response_model=PaginatedEnvelope[PartnershipOut], summary="Agreement portfolio")
async def list_partnerships(
    search: str | None = None,
    stakeholder_id: str | None = Query(None, alias="stakeholderId"),
    status_filter: str | None = Query(None, alias="status"),
    owner: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    query = select(PartnershipAgreement)
    if stakeholder_id:
        query = query.where(PartnershipAgreement.stakeholder_id == parse_uuid(stakeholder_id, label="stakeholder"))
    if status_filter:
        query = query.where(PartnershipAgreement.status == status_filter)
    if owner:
        query = query.where(PartnershipAgreement.owner == owner)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(PartnershipAgreement.title).like(term),
                func.lower(PartnershipAgreement.reference).like(term),
                func.lower(PartnershipAgreement.owner).like(term),
            )
        )
    count = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(query.order_by(PartnershipAgreement.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return paginated([svc.serialize_agreement(r) for r in rows], count=count, page=page, page_size=page_size)


@router.get("/partnerships/integrations/health", response_model=Envelope[list[IntegrationHealthOut]])
async def integration_health(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    settings = get_settings()
    pending = {
        target: await db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.target_system == target, OutboxEvent.status != OutboxStatus.SENT)
        )
        or 0
        for target in ("S074", "S203", "S204", "S225")
    }

    def relay(system: str, name: str, url: str, purpose: str) -> dict:
        state = "CONTRACT_READY" if url else "PENDING"
        detail = f"{purpose} {pending.get(system, 0)} message(s) awaiting delivery."
        if not url:
            detail += " Endpoint not configured; messages are held in the outbox."
        return {"system": system, "name": name, "state": state, "last_checked_at": utcnow(), "detail": detail}

    return ok(
        [
            {
                "system": "S003",
                "name": "Records management",
                "state": "REFERENCE_ONLY",
                "last_checked_at": None,
                "detail": "Signed documents and evidence are stored as S003 references.",
            },
            relay("S074", "Comms system", settings.S074_COMMS_URL, "Renewal alerts and reminders."),
            {
                "system": "S136",
                "name": "Contract lifecycle",
                "state": "REFERENCE_ONLY",
                "last_checked_at": None,
                "detail": "Legal contracts are linked by S136 reference.",
            },
            relay(
                "S203",
                "Screening & due diligence",
                settings.S203_SCREENING_URL,
                "Screening requests are sent from S081 and decisions gate agreement activation.",
            ),
            relay("S204", "Audit logging", settings.S204_AUDIT_URL, "Hash-chained audit events."),
            {
                "system": "S217",
                "name": "API gateway",
                "state": "CONTRACT_READY",
                "last_checked_at": utcnow(),
                "detail": "Same-origin /api/v1 with cookie sessions.",
            },
            relay("S225", "Analytics", settings.S225_ANALYTICS_URL, "Portfolio extracts."),
        ]
    )


@router.get("/partnerships/{agreement_id}", response_model=Envelope[PartnershipOut])
async def get_partnership(
    agreement_id: str, response: Response, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)
):
    return await _respond(db, parse_uuid(agreement_id, label="agreement"), response)


@router.post("/partnerships", response_model=Envelope[PartnershipOut], status_code=201)
async def create_partnership(
    body: PartnershipCreate, response: Response, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_CREATE)
):
    if body.id and await db.get(PartnershipAgreement, body.id):
        raise Conflict("An agreement with this ID already exists.", code="DUPLICATE_ID")
    parties = await svc.validate_parties(db, body.stakeholder_id, body.party_stakeholder_ids)
    clash = await db.scalar(
        select(PartnershipAgreement).where(
            PartnershipAgreement.stakeholder_id == body.stakeholder_id,
            func.lower(PartnershipAgreement.title) == body.title.lower(),
            PartnershipAgreement.status != S.TERMINATED,
        )
    )
    if clash is not None:
        raise Conflict(
            f"{clash.reference} already covers this stakeholder and title.",
            code="DUPLICATE_AGREEMENT",
            extra={"duplicateId": str(clash.id)},
        )
    agreement = PartnershipAgreement(
        stakeholder_id=body.stakeholder_id,
        party_stakeholder_ids=parties,
        reference=await svc.next_reference(db, dt.date.today().year),
        title=body.title,
        agreement_type=body.agreement_type,
        owner=body.owner,
        effective_date=body.effective_date,
        expiry_date=body.expiry_date,
        value_commitment=body.value_commitment,
        deliverables=body.deliverables,
        legal_contract_ref=body.legal_contract_ref,
    )
    if body.id:
        agreement.id = body.id
    db.add(agreement)
    await db.flush()
    svc.add_history(db, agreement.id, "CREATED", "Partnership record created.", identity.display)
    await _audit(db, identity, AuditAction.PARTNERSHIP_CREATED, agreement)
    await db.commit()
    return await _respond(db, agreement.id, response)


@router.patch("/partnerships/{agreement_id}", response_model=Envelope[PartnershipOut])
async def update_partnership(
    agreement_id: str,
    body: PartnershipUpdate,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_EDIT),
):
    agreement = await _agreement(db, agreement_id)
    svc.check_version(agreement, if_match)
    if agreement.status in (S.TERMINATED, S.EXPIRED):
        raise Conflict("Closed agreements cannot be edited.", code="AGREEMENT_CLOSED")
    if agreement.status == S.ACTIVE and (
        body.effective_date != agreement.effective_date or body.expiry_date != agreement.expiry_date
    ):
        raise Conflict("Change an active agreement's term through a renewal.", code="USE_RENEWAL")
    before = _snapshot(agreement)
    agreement.party_stakeholder_ids = await svc.validate_parties(db, body.stakeholder_id, body.party_stakeholder_ids)
    agreement.stakeholder_id = body.stakeholder_id
    agreement.title, agreement.agreement_type, agreement.owner = body.title, body.agreement_type, body.owner
    agreement.effective_date, agreement.expiry_date = body.effective_date, body.expiry_date
    agreement.value_commitment, agreement.deliverables = body.value_commitment, body.deliverables
    agreement.legal_contract_ref, agreement.signed_document_ref = body.legal_contract_ref, body.signed_document_ref
    svc.touch(agreement)
    svc.add_history(db, agreement.id, "UPDATED", "Agreement details updated.", identity.display)
    await _audit(db, identity, AuditAction.PARTNERSHIP_UPDATED, agreement, before=before)
    await db.commit()
    return await _respond(db, agreement.id, response)


@router.post("/partnerships/{agreement_id}/status", response_model=Envelope[PartnershipOut])
async def transition_partnership(
    agreement_id: str,
    body: TransitionIn,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_LIFECYCLE),
):
    agreement = await _agreement(db, agreement_id)
    svc.check_version(agreement, if_match)
    if body.status not in svc.ALLOWED_TRANSITIONS.get(agreement.status, set()):
        raise Conflict(f"An agreement cannot move from {agreement.status} to {body.status}.", code="INVALID_TRANSITION")
    blockers = await svc.transition_blockers(db, agreement, body.status)
    if blockers:
        raise Conflict(blockers[0], code="TRANSITION_BLOCKED", extra={"blockers": blockers})
    before = _snapshot(agreement)
    agreement.status = body.status
    svc.touch(agreement)
    if body.status == S.ACTIVE:
        await svc.link_stakeholders_on_activation(db, agreement)
        if not await svc.open_alerts(db, agreement.id):
            for alert in svc.build_renewal_alerts(agreement, get_settings().RENEWAL_ALERT_DEFAULT_RECIPIENTS):
                db.add(alert)
    if body.status == S.EXPIRED:
        await svc.cancel_open_alerts(db, agreement.id)
    action = "EXPIRED" if body.status == S.EXPIRED else "STATUS_CHANGED"
    svc.add_history(db, agreement.id, action, f"Lifecycle status changed to {body.status}. {body.note}".strip(), identity.display)
    await _audit(db, identity, AuditAction.PARTNERSHIP_STATUS_CHANGED, agreement, before=before, summary=body.note)
    await db.commit()
    return await _respond(db, agreement.id, response)


@router.post("/partnerships/{agreement_id}/renewals", response_model=Envelope[PartnershipOut])
async def renew_partnership(
    agreement_id: str,
    body: RenewIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_LIFECYCLE),
):
    agreement = await _agreement(db, agreement_id)
    if agreement.status not in (S.ACTIVE, S.RENEWAL_DUE, S.EXPIRED):
        raise Conflict("Only active, renewal-due or expired agreements can be renewed.", code="INVALID_TRANSITION")
    if agreement.expiry_date and body.effective_date < agreement.expiry_date - dt.timedelta(days=366):
        raise ValidationFailed(
            "The renewed term must start near the current expiry.", field_errors={"effectiveDate": ["Too early."]}
        )
    blockers = await svc.party_blockers(db, agreement.party_stakeholder_ids)
    if blockers:
        raise Conflict(blockers[0], code="TRANSITION_BLOCKED", extra={"blockers": blockers})
    before = _snapshot(agreement)
    db.add(
        PartnershipRenewal(
            agreement_id=agreement.id,
            previous_effective_date=agreement.effective_date,
            previous_expiry_date=agreement.expiry_date,
            previous_legal_contract_ref=agreement.legal_contract_ref,
            previous_signed_document_ref=agreement.signed_document_ref,
            effective_date=body.effective_date,
            expiry_date=body.expiry_date,
            legal_contract_ref=body.legal_contract_ref,
            signed_document_ref=body.signed_document_ref,
            terms_summary=body.terms_summary,
            renewed_by=identity.display,
        )
    )
    recipients = await svc.cancel_open_alerts(db, agreement.id) or get_settings().RENEWAL_ALERT_DEFAULT_RECIPIENTS
    agreement.effective_date, agreement.expiry_date = body.effective_date, body.expiry_date
    agreement.legal_contract_ref, agreement.signed_document_ref = body.legal_contract_ref, body.signed_document_ref
    agreement.status = S.ACTIVE
    agreement.renewal_count += 1
    svc.touch(agreement)
    for alert in svc.build_renewal_alerts(agreement, recipients):
        db.add(alert)
    svc.add_history(db, agreement.id, "RENEWED", f"Agreement renewed to {body.expiry_date.isoformat()}.", identity.display)
    await _audit(db, identity, AuditAction.PARTNERSHIP_RENEWED, agreement, before=before)
    await db.commit()
    return await _respond(db, agreement.id, response)


@router.post("/partnerships/{agreement_id}/termination", response_model=Envelope[PartnershipOut])
async def terminate_partnership(
    agreement_id: str,
    body: TerminateIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_LIFECYCLE),
):
    agreement = await _agreement(db, agreement_id)
    if agreement.status == S.TERMINATED:
        raise Conflict("This agreement is already terminated.", code="INVALID_TRANSITION")
    blockers = svc.termination_blockers(agreement)
    if blockers:
        raise Conflict(blockers[0], code="TERMINATION_BLOCKED", extra={"blockers": blockers})
    before = _snapshot(agreement)
    agreement.status = S.TERMINATED
    agreement.termination = {
        "terminatedAt": body.terminated_at.isoformat(),
        "reason": body.reason,
        "documentationRef": body.documentation_ref,
        "finalArchiveRef": body.final_archive_ref,
        "approvedBy": identity.display,
    }
    svc.touch(agreement)
    await svc.cancel_open_alerts(db, agreement.id)
    svc.add_history(db, agreement.id, "TERMINATED", f"Agreement terminated: {body.reason}", identity.display)
    await _audit(db, identity, AuditAction.PARTNERSHIP_TERMINATED, agreement, before=before)
    await db.commit()
    return await _respond(db, agreement.id, response)


@router.post("/partnerships/imports", response_model=Envelope[PartnershipImportResult], summary="Legacy migration")
async def import_partnerships(
    body: PartnershipImportIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_IMPORT)
):
    imported = skipped = 0
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(body.agreements, start=1):
        reference = row.reference.strip()
        if reference.lower() in seen or await db.scalar(
            select(PartnershipAgreement.id).where(func.lower(PartnershipAgreement.reference) == reference.lower())
        ):
            skipped += 1
            errors.append(f"Row {index}: reference {reference} already exists.")
            continue
        try:
            parties = await svc.validate_parties(db, row.stakeholder_id, row.party_stakeholder_ids)
        except ValidationFailed:
            skipped += 1
            errors.append(f"Row {index}: stakeholder is not in S081.")
            continue
        if row.status == S.ACTIVE and not (row.signed_document_ref and row.legal_contract_ref and row.expiry_date):
            skipped += 1
            errors.append(f"Row {index}: active agreements need S136, S003 and expiry references.")
            continue
        agreement = PartnershipAgreement(
            stakeholder_id=row.stakeholder_id,
            party_stakeholder_ids=parties,
            reference=reference,
            title=row.title,
            agreement_type=row.agreement_type,
            status=row.status,
            owner=row.owner,
            effective_date=row.effective_date,
            expiry_date=row.expiry_date,
            value_commitment=row.value_commitment,
            deliverables=row.deliverables,
            legal_contract_ref=row.legal_contract_ref,
            signed_document_ref=row.signed_document_ref,
        )
        db.add(agreement)
        await db.flush()
        svc.add_history(db, agreement.id, "CREATED", "Imported from the legacy register.", identity.display)
        if row.status == S.ACTIVE:
            for alert in svc.build_renewal_alerts(agreement, get_settings().RENEWAL_ALERT_DEFAULT_RECIPIENTS):
                db.add(alert)
        seen.add(reference.lower())
        imported += 1
    await emit_audit(
        db,
        action=AuditAction.PARTNERSHIPS_IMPORTED,
        resource_type=ResourceType.PARTNERSHIP,
        identity=identity,
        summary=f"Import: {imported} imported, {skipped} skipped.",
        after={"imported": imported, "skipped": skipped, "rows": len(body.agreements)},
    )
    await db.commit()
    return ok({"imported": imported, "skipped": skipped, "errors": errors})


# ── Obligations ──


async def _obligation(db: AsyncSession, obligation_id: str) -> PartnershipObligation:
    row = await db.get(PartnershipObligation, parse_uuid(obligation_id, label="obligation"))
    if row is None:
        raise NotFound("That obligation does not exist.")
    return row


def _require_evidence(status: str, evidence: list[str]) -> None:
    if status == ObligationStatus.COMPLETED and not evidence:
        raise ValidationFailed(
            "Attach at least one S003 evidence reference before completing an obligation.",
            field_errors={"evidenceReferences": ["Required to complete."]},
        )


@router.get("/partnerships/{agreement_id}/obligations", response_model=Envelope[list[ObligationOut]])
async def list_obligations(agreement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    agreement = await _agreement(db, agreement_id)
    return ok([svc.serialize_obligation(o) for o in sorted(agreement.obligations, key=lambda o: o.due_date)])


@router.post("/partnerships/{agreement_id}/obligations", response_model=Envelope[ObligationOut], status_code=201)
async def create_obligation(
    agreement_id: str, body: ObligationCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_OBLIGATIONS)
):
    agreement = await _agreement(db, agreement_id)
    if agreement.status in (S.TERMINATED, S.EXPIRED):
        raise Conflict("Closed agreements cannot take new obligations.", code="AGREEMENT_CLOSED")
    obligation = PartnershipObligation(
        agreement_id=agreement.id,
        title=body.title,
        description=body.description,
        owner=body.owner,
        due_date=body.due_date,
        reminder_lead_days=body.reminder_lead_days,
        escalation_owner=body.escalation_owner,
    )
    if body.id:
        if await db.get(PartnershipObligation, body.id):
            raise Conflict("An obligation with this ID already exists.", code="DUPLICATE_ID")
        obligation.id = body.id
    db.add(obligation)
    await db.flush()
    svc.add_history(db, agreement.id, "OBLIGATION_UPDATED", f"Obligation added: {body.title}.", identity.display)
    await emit_audit(
        db,
        action=AuditAction.OBLIGATION_CREATED,
        resource_type=ResourceType.OBLIGATION,
        resource_id=obligation.id,
        identity=identity,
        after={"title": body.title, "dueDate": body.due_date},
    )
    await db.commit()
    await db.refresh(obligation)
    return ok(svc.serialize_obligation(obligation))


@router.patch("/partnership-obligations/{obligation_id}", response_model=Envelope[ObligationOut])
async def update_obligation(
    obligation_id: str, body: ObligationUpdate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_OBLIGATIONS)
):
    obligation = await _obligation(db, obligation_id)
    status = ObligationStatus.IN_PROGRESS if body.status == ObligationStatus.OVERDUE else body.status
    _require_evidence(status, body.evidence_references)
    before = {"status": obligation.status, "dueDate": obligation.due_date}
    obligation.title, obligation.description, obligation.owner = body.title, body.description, body.owner
    obligation.due_date, obligation.status = body.due_date, status
    obligation.evidence_references = body.evidence_references
    obligation.reminder_lead_days, obligation.escalation_owner = body.reminder_lead_days, body.escalation_owner
    obligation.updated_at = utcnow()
    svc.add_history(
        db, obligation.agreement_id, "OBLIGATION_UPDATED", f"Obligation updated: {body.title} ({status}).", identity.display
    )
    await emit_audit(
        db,
        action=AuditAction.OBLIGATION_UPDATED,
        resource_type=ResourceType.OBLIGATION,
        resource_id=obligation.id,
        identity=identity,
        before=before,
        after={"status": status, "dueDate": body.due_date},
    )
    await db.commit()
    await db.refresh(obligation)
    return ok(svc.serialize_obligation(obligation))


@router.get("/partnership-obligations/{obligation_id}/progress", response_model=Envelope[list[ProgressOut]])
async def list_progress(obligation_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    obligation = await _obligation(db, obligation_id)
    rows = await db.scalars(
        select(ObligationProgressNote)
        .where(ObligationProgressNote.obligation_id == obligation.id)
        .order_by(ObligationProgressNote.created_at.desc())
    )
    return ok(list(rows.all()))


@router.post("/partnership-obligations/{obligation_id}/progress", response_model=Envelope[ProgressOut], status_code=201)
async def add_progress(
    obligation_id: str, body: ProgressIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_OBLIGATIONS)
):
    obligation = await _obligation(db, obligation_id)
    status = ObligationStatus.IN_PROGRESS if body.status == ObligationStatus.OVERDUE else body.status
    _require_evidence(status, obligation.evidence_references)
    note = ObligationProgressNote(obligation_id=obligation.id, note=body.note, status=status, actor=identity.display)
    obligation.status = status
    obligation.updated_at = utcnow()
    db.add(note)
    svc.add_history(
        db, obligation.agreement_id, "OBLIGATION_UPDATED", f"Progress on {obligation.title}: {body.note}", identity.display
    )
    await emit_audit(
        db,
        action=AuditAction.OBLIGATION_PROGRESS_ADDED,
        resource_type=ResourceType.OBLIGATION,
        resource_id=obligation.id,
        identity=identity,
        after={"status": status},
    )
    await db.commit()
    await db.refresh(note)
    return ok(note)


# ── Reviews ──


@router.get("/partnerships/{agreement_id}/reviews", response_model=Envelope[list[ReviewOut]])
async def list_reviews(agreement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    agreement = await _agreement(db, agreement_id)
    rows = await db.scalars(
        select(PartnershipReview)
        .where(PartnershipReview.agreement_id == agreement.id)
        .order_by(PartnershipReview.review_date.desc())
    )
    return ok(list(rows.all()))


def _apply_review(review: PartnershipReview, body: ReviewIn) -> None:
    for field in (
        "review_date",
        "reviewer",
        "outcome",
        "summary",
        "period_start",
        "period_end",
        "outputs",
        "strategic_score",
        "issues",
        "recommendations",
        "renewal_recommendation",
        "next_review_date",
    ):
        setattr(review, field, getattr(body, field))


@router.post("/partnerships/{agreement_id}/reviews", response_model=Envelope[ReviewOut], status_code=201)
async def create_review(
    agreement_id: str, body: ReviewCreate, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_REVIEWS)
):
    agreement = await _agreement(db, agreement_id)
    review = PartnershipReview(agreement_id=agreement.id)
    _apply_review(review, body)
    if body.id:
        if await db.get(PartnershipReview, body.id):
            raise Conflict("A review with this ID already exists.", code="DUPLICATE_ID")
        review.id = body.id
    db.add(review)
    await db.flush()
    svc.add_history(db, agreement.id, "REVIEW_UPDATED", f"Value review recorded ({body.outcome}).", identity.display)
    await emit_audit(
        db,
        action=AuditAction.REVIEW_CREATED,
        resource_type=ResourceType.REVIEW,
        resource_id=review.id,
        identity=identity,
        after={"outcome": body.outcome, "score": body.strategic_score},
    )
    await db.commit()
    await db.refresh(review)
    return ok(review)


@router.patch("/partnership-reviews/{review_id}", response_model=Envelope[ReviewOut])
async def update_review(
    review_id: str, body: ReviewIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_REVIEWS)
):
    review = await db.get(PartnershipReview, parse_uuid(review_id, label="review"))
    if review is None:
        raise NotFound("That review does not exist.")
    before = {"outcome": review.outcome, "score": review.strategic_score}
    _apply_review(review, body)
    svc.add_history(db, review.agreement_id, "REVIEW_UPDATED", "Value review updated.", identity.display)
    await emit_audit(
        db,
        action=AuditAction.REVIEW_UPDATED,
        resource_type=ResourceType.REVIEW,
        resource_id=review.id,
        identity=identity,
        before=before,
        after={"outcome": body.outcome, "score": body.strategic_score},
    )
    await db.commit()
    await db.refresh(review)
    return ok(review)


# ── Renewals & alerts ──


@router.get("/partnerships/{agreement_id}/renewals", response_model=Envelope[list[RenewalOut]])
async def list_renewals(agreement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    agreement = await _agreement(db, agreement_id)
    rows = await db.scalars(
        select(PartnershipRenewal)
        .where(PartnershipRenewal.agreement_id == agreement.id)
        .order_by(PartnershipRenewal.renewed_at.desc())
    )
    return ok(list(rows.all()))


@router.get("/partnerships/{agreement_id}/renewal-alerts", response_model=Envelope[list[RenewalAlertOut]])
async def list_alerts(agreement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    agreement = await _agreement(db, agreement_id)
    rows = await db.scalars(
        select(PartnershipRenewalAlert)
        .where(PartnershipRenewalAlert.agreement_id == agreement.id)
        .order_by(PartnershipRenewalAlert.scheduled_for)
    )
    return ok([svc.serialize_alert(a) for a in rows.all()])


@router.put("/partnerships/{agreement_id}/renewal-alerts", response_model=Envelope[list[RenewalAlertOut]])
async def configure_alerts(
    agreement_id: str, body: AlertsConfigIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_LIFECYCLE)
):
    agreement = await _agreement(db, agreement_id)
    if agreement.expiry_date is None:
        raise ValidationFailed("Set an expiry date before configuring renewal alerts.")
    if agreement.status in (S.TERMINATED, S.EXPIRED):
        raise Conflict("Closed agreements have no renewal alerts.", code="AGREEMENT_CLOSED")
    await svc.cancel_open_alerts(db, agreement.id)
    alerts = svc.build_renewal_alerts(agreement, body.recipients)
    db.add_all(alerts)
    plural = "" if len(body.recipients) == 1 else "s"
    svc.add_history(
        db,
        agreement.id,
        "RENEWAL_ALERT_UPDATED",
        f"Renewal alerts configured for {len(body.recipients)} recipient{plural}.",
        identity.display,
    )
    await emit_audit(
        db,
        action=AuditAction.RENEWAL_ALERTS_CONFIGURED,
        resource_type=ResourceType.PARTNERSHIP,
        resource_id=agreement.id,
        identity=identity,
        after={"recipients": body.recipients},
    )
    await db.commit()
    return ok([svc.serialize_alert(a) for a in alerts])


async def _alert(db: AsyncSession, alert_id: str) -> PartnershipRenewalAlert:
    alert = await db.get(PartnershipRenewalAlert, parse_uuid(alert_id, label="alert"))
    if alert is None:
        raise NotFound("That renewal alert does not exist.")
    return alert


@router.post("/partnership-renewal-alerts/{alert_id}/dispatch", response_model=Envelope[RenewalAlertOut])
async def dispatch_alert(alert_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_LIFECYCLE)):
    alert = await _alert(db, alert_id)
    if svc.effective_alert_status(alert) not in (RenewalAlertStatus.DUE, RenewalAlertStatus.FAILED):
        raise Conflict("Only due or failed alerts can be dispatched.", code="ALERT_NOT_DUE")
    agreement = await svc.load_agreement(db, alert.agreement_id)
    message = await enqueue(
        db,
        target_system="S074",
        event_type="partnership.renewal_alert",
        payload={
            "recipients": alert.recipients,
            "template": "s082-renewal-alert",
            "placeholders": {
                "reference": agreement.reference,
                "title": agreement.title,
                "expiryDate": agreement.expiry_date,
                "milestoneDays": alert.milestone_days,
            },
        },
        idempotency_key=f"s082-alert:{alert.id}:{alert.sent_at or 'first'}",
    )
    alert.status = RenewalAlertStatus.SENT
    alert.sent_at = utcnow()
    alert.communication_ref = f"S074-OUTBOX-{message.id.hex[:12].upper()}"
    svc.add_history(
        db,
        alert.agreement_id,
        "RENEWAL_ALERT_UPDATED",
        f"{alert.milestone_days}-day renewal alert dispatched through S074.",
        identity.display,
    )
    await emit_audit(
        db,
        action=AuditAction.RENEWAL_ALERT_DISPATCHED,
        resource_type=ResourceType.RENEWAL_ALERT,
        resource_id=alert.id,
        identity=identity,
        after={"communicationRef": alert.communication_ref},
    )
    await db.commit()
    return ok(svc.serialize_alert(alert))


@router.post("/partnership-renewal-alerts/{alert_id}/acknowledgement", response_model=Envelope[RenewalAlertOut])
async def acknowledge_alert(alert_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    alert = await _alert(db, alert_id)
    if alert.status != RenewalAlertStatus.SENT:
        raise Conflict("Only sent alerts can be acknowledged.", code="ALERT_NOT_SENT")
    alert.status = RenewalAlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = identity.display
    svc.add_history(
        db,
        alert.agreement_id,
        "RENEWAL_ALERT_UPDATED",
        f"{alert.milestone_days}-day renewal alert acknowledged.",
        identity.display,
    )
    await emit_audit(
        db,
        action=AuditAction.RENEWAL_ALERT_ACKNOWLEDGED,
        resource_type=ResourceType.RENEWAL_ALERT,
        resource_id=alert.id,
        identity=identity,
    )
    await db.commit()
    return ok(svc.serialize_alert(alert))


# ── History & audit ──


@router.get("/partnerships/{agreement_id}/history", response_model=Envelope[list[HistoryOut]])
async def agreement_history(agreement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    agreement = await _agreement(db, agreement_id)
    rows = await db.scalars(
        select(PartnershipHistory)
        .where(PartnershipHistory.agreement_id == agreement.id)
        .order_by(PartnershipHistory.occurred_at.desc())
    )
    return ok(list(rows.all()))


@router.get("/partnership-audit-events", response_model=PaginatedEnvelope[HistoryOut])
async def partnership_audit_events(
    stakeholder_id: str | None = Query(None, alias="stakeholderId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_EXPORT),
):
    query = select(PartnershipHistory)
    if stakeholder_id:
        query = query.join(PartnershipAgreement, PartnershipAgreement.id == PartnershipHistory.agreement_id).where(
            PartnershipAgreement.stakeholder_id == parse_uuid(stakeholder_id, label="stakeholder")
        )
    count = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.scalars(query.order_by(PartnershipHistory.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return paginated(list(rows), count=count, page=page, page_size=page_size)


__all__ = ["router", "Stakeholder"]
