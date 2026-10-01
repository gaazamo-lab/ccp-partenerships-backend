"""
S084 Visa & Travel Authorisation endpoints.

Record scope matters here in a way it does not elsewhere: a traveller sees only
their own requests, while operators, approvers and auditors see the queue. That
is applied in `_scope`, on every read, rather than left to the client.

State rules live in `app.services.travel`; this module owns transactions,
permissions and audit.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.audit import emit_audit
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, parse_uuid, require_permission
from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.rbac import P, has_permission
from app.models.travel import TravelPolicy, TravelRequest
from app.schemas.common import Envelope, ok
from app.schemas.travel import (
    AmendmentIn,
    ApprovalDecisionIn,
    CancelIn,
    ClosureIn,
    EstimateIn,
    EvidenceIn,
    IntegrationIn,
    IssueDocumentIn,
    TravelPolicyIn,
    TravelPolicyOut,
    TravelRequestIn,
    TravelRequestOut,
)
from app.services import travel as rules

router = APIRouter(tags=["S084 Travel authorisation"])

_READ = require_permission(P.TRAVEL_READ)
_CREATE = require_permission(P.TRAVEL_CREATE)
_OPERATE = require_permission(P.TRAVEL_OPERATE)
_APPROVE = require_permission(P.TRAVEL_APPROVE)
_CONFIGURE = require_permission(P.TRAVEL_CONFIGURE)


def _sees_every_request(identity: Identity) -> bool:
    """A traveller is scoped to their own records; every other role sees the queue."""
    return any(
        has_permission(identity.permissions, permission)
        for permission in (P.TRAVEL_OPERATE, P.TRAVEL_APPROVE, P.TRAVEL_CONFIGURE, P.AUDIT_READ)
    )


def _scope(query: Select, identity: Identity) -> Select:
    if _sees_every_request(identity):
        return query
    return query.where(
        or_(
            func.lower(TravelRequest.traveller) == identity.name.lower(),
            func.lower(TravelRequest.requester) == identity.name.lower(),
        )
    )


async def _request(db: AsyncSession, request_id: str, identity: Identity) -> TravelRequest:
    row = await db.get(TravelRequest, parse_uuid(request_id, label="travel request"))
    if row is None:
        raise NotFound("That travel request does not exist.", code="TRAVEL_REQUEST_NOT_FOUND")
    if not _sees_every_request(identity):
        owned = identity.name.lower() in {
            (row.traveller or "").lower(),
            (row.requester or "").lower(),
        }
        # Same response as a genuine miss: a traveller must not be able to probe
        # for requests belonging to other people.
        if not owned:
            raise NotFound("That travel request does not exist.", code="TRAVEL_REQUEST_NOT_FOUND")
    return row


async def _next_reference(db: AsyncSession) -> str:
    year = dt.date.today().year
    prefix = f"S084-{year}-"
    latest = await db.scalar(select(func.max(TravelRequest.reference)).where(TravelRequest.reference.like(f"{prefix}%")))
    sequence = int(latest.rsplit("-", 1)[1]) + 1 if latest else 1
    return f"{prefix}{sequence:04d}"


async def _policy(db: AsyncSession) -> TravelPolicy:
    row = await db.scalar(select(TravelPolicy).limit(1))
    if row is None:
        row = TravelPolicy(daily_rates={"Regional": 1200.0, "Continental": 1800.0, "International": 2400.0})
        db.add(row)
        await db.flush()
    return row


async def _audit_and_commit(
    db: AsyncSession,
    request: TravelRequest,
    identity: Identity,
    action: str,
    after: dict[str, Any],
    before: dict[str, Any] | None = None,
) -> TravelRequest:
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.TRAVEL_REQUEST,
        resource_id=request.id,
        identity=identity,
        before=before,
        after=after,
    )
    await db.commit()
    await db.refresh(request)
    return request


# ── Requests ──


@router.get("/travel-requests", response_model=Envelope[list[TravelRequestOut]])
async def list_requests(
    status_filter: str | None = Query(None, alias="status"),
    direction: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    query = select(TravelRequest).order_by(TravelRequest.created_at.desc())
    if status_filter:
        query = query.where(TravelRequest.status == status_filter)
    if direction:
        query = query.where(TravelRequest.direction == direction)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(TravelRequest.traveller).like(term),
                func.lower(TravelRequest.destination).like(term),
                func.lower(TravelRequest.reference).like(term),
            )
        )
    return ok(list((await db.scalars(_scope(query, identity))).all()))


@router.get("/travel-requests/{request_id}", response_model=Envelope[TravelRequestOut])
async def get_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    return ok(await _request(db, request_id, identity))


@router.post("/travel-requests", response_model=Envelope[TravelRequestOut], status_code=201)
async def create_request(
    body: TravelRequestIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CREATE),
):
    if body.direction == "Inbound" and not (body.nationality or "").strip():
        raise ValidationFailed(
            "Nationality is required for inbound support.",
            field_errors={"nationality": ["Required for inbound support."]},
        )

    if body.id and await db.get(TravelRequest, body.id):
        raise Conflict("A travel request with this ID already exists.", code="DUPLICATE_ID")

    policy = await _policy(db)
    request = TravelRequest(
        reference=await _next_reference(db),
        **body.model_dump(exclude={"id"}),
        owner=body.traveller,
        requester=identity.name,
        status="Draft",
        policy_version=policy.policy_version,
        record_version=1,
        evidence=rules.evidence_for(body.direction, body.category),
        approvals=rules.approvals_for(body.direction, body.category),
        integrations=rules.integrations_for(body.direction),
        issued_documents=[],
        notifications=[],
        history=[],
    )
    if body.id:
        request.id = body.id
    rules.record(request, "Request raised", f"{identity.name} created the request.")
    db.add(request)
    await db.flush()
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_REQUEST_CREATED,
            {"reference": request.reference, "direction": request.direction, "category": request.category},
        )
    )


@router.put("/travel-requests/{request_id}", response_model=Envelope[TravelRequestOut])
async def update_request(
    request_id: str,
    body: TravelRequestIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CREATE),
):
    request = await _request(db, request_id, identity)
    if request.status not in rules.EDITABLE:
        raise ValidationFailed(
            "Only a draft or returned request can be edited. Use an amendment instead.",
            code="TRAVEL_NOT_EDITABLE",
        )
    before = {"destination": request.destination, "status": request.status}
    for key, value in body.model_dump(exclude={"id"}).items():
        setattr(request, key, value)
    rules.record(request, "Request updated", f"{identity.name} edited the request.")
    return ok(
        await _audit_and_commit(
            db, request, identity, AuditAction.TRAVEL_REQUEST_UPDATED, {"destination": request.destination}, before
        )
    )


@router.put("/travel-requests/{request_id}/evidence/{index}", response_model=Envelope[TravelRequestOut])
async def set_evidence(
    request_id: str,
    index: int,
    body: EvidenceIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CREATE),
):
    request = await _request(db, request_id, identity)
    rules.set_evidence(request, index, body.status, body.detail, identity.name)
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_EVIDENCE_RECORDED,
            {"index": index, "status": body.status},
        )
    )


@router.post("/travel-requests/{request_id}/advance", response_model=Envelope[TravelRequestOut])
async def advance_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_READ),
):
    request = await _request(db, request_id, identity)
    # A traveller may submit their own draft; every later step needs an operator.
    if request.status not in rules.EDITABLE and not has_permission(identity.permissions, P.TRAVEL_OPERATE):
        raise Forbidden("Your role cannot move this request forward.")
    before = {"status": request.status}
    target = rules.advance(request, identity.name)
    return ok(await _audit_and_commit(db, request, identity, AuditAction.TRAVEL_STATUS_CHANGED, {"status": target}, before))


@router.post("/travel-requests/{request_id}/approvals/{approval_id}", response_model=Envelope[TravelRequestOut])
async def decide_approval(
    request_id: str,
    approval_id: str,
    body: ApprovalDecisionIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_APPROVE),
):
    request = await _request(db, request_id, identity)
    before = {"status": request.status}
    rules.apply_decision(request, approval_id, body.decision, body.comment, identity.name)
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_APPROVAL_DECIDED,
            {"approvalId": approval_id, "decision": body.decision, "status": request.status},
            before,
        )
    )


@router.put("/travel-requests/{request_id}/estimate", response_model=Envelope[TravelRequestOut])
async def save_estimate(
    request_id: str,
    body: EstimateIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_OPERATE),
):
    request = await _request(db, request_id, identity)
    rules.save_estimate(request, body.model_dump(), identity.name)
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_ESTIMATE_SAVED,
            {"rateVersion": body.rate_version, "eligibleDays": body.eligible_days},
        )
    )


@router.post("/travel-requests/{request_id}/documents", response_model=Envelope[TravelRequestOut])
async def issue_document(
    request_id: str,
    body: IssueDocumentIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_OPERATE),
):
    request = await _request(db, request_id, identity)
    issued = rules.issue_document(request, body.signatory, body.template_version, identity.name)
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_DOCUMENT_ISSUED,
            {"reference": issued["reference"], "type": issued["type"]},
        )
    )


@router.post("/travel-requests/{request_id}/amendments", response_model=Envelope[TravelRequestOut])
async def amend_request(
    request_id: str,
    body: AmendmentIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_OPERATE),
):
    request = await _request(db, request_id, identity)
    before = {"destination": request.destination, "status": request.status}
    rules.amend(request, body.destination, body.start_date, body.end_date, body.reason, identity.name)
    return ok(
        await _audit_and_commit(db, request, identity, AuditAction.TRAVEL_AMENDED, {"destination": body.destination}, before)
    )


@router.post("/travel-requests/{request_id}/cancellation", response_model=Envelope[TravelRequestOut])
async def cancel_request(
    request_id: str,
    body: CancelIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CREATE),
):
    request = await _request(db, request_id, identity)
    before = {"status": request.status}
    rules.cancel(request, body.reason, identity.name)
    return ok(await _audit_and_commit(db, request, identity, AuditAction.TRAVEL_CANCELLED, {"reason": body.reason}, before))


@router.post("/travel-requests/{request_id}/closure", response_model=Envelope[TravelRequestOut])
async def close_request(
    request_id: str,
    body: ClosureIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_OPERATE),
):
    request = await _request(db, request_id, identity)
    before = {"status": request.status}
    rules.close(request, body.model_dump(by_alias=True), identity.name)
    return ok(await _audit_and_commit(db, request, identity, AuditAction.TRAVEL_CLOSED, {"outcome": body.outcome}, before))


@router.put("/travel-requests/{request_id}/integrations", response_model=Envelope[TravelRequestOut])
async def update_integration(
    request_id: str,
    body: IntegrationIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_OPERATE),
):
    request = await _request(db, request_id, identity)
    rules.set_integration(request, body.system, body.status, body.reference, body.note, identity.name)
    return ok(
        await _audit_and_commit(
            db,
            request,
            identity,
            AuditAction.TRAVEL_INTEGRATION_UPDATED,
            {"system": body.system, "status": body.status},
        )
    )


# ── Policy ──


@router.get("/travel-policy", response_model=Envelope[TravelPolicyOut])
async def get_policy(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    policy = await _policy(db)
    await db.commit()
    return ok(policy)


@router.put("/travel-policy", response_model=Envelope[TravelPolicyOut])
async def update_policy(
    body: TravelPolicyIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CONFIGURE),
):
    policy = await _policy(db)
    before = {"policyVersion": policy.policy_version, "rateVersion": policy.rate_version}
    for key, value in body.model_dump().items():
        setattr(policy, key, value)
    policy.updated_by = identity.name
    await emit_audit(
        db,
        action=AuditAction.TRAVEL_POLICY_UPDATED,
        resource_type=ResourceType.TRAVEL_POLICY,
        resource_id=policy.id,
        identity=identity,
        before=before,
        after={"policyVersion": body.policy_version, "rateVersion": body.rate_version},
    )
    await db.commit()
    await db.refresh(policy)
    return ok(policy)
