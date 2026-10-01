"""
S083 International Relations & Protocols Workspace endpoints.

JSON sub-collections are copied, changed and reassigned (never mutated in
place) so SQLAlchemy persists them.
"""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import emit_audit, enqueue
from app.core.audit_events import AuditAction, ResourceType
from app.core.auth import Identity, parse_uuid, require_any_permission, require_permission
from app.core.database import get_db
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.rbac import P
from app.models.audit import OutboxEvent, OutboxStatus
from app.models.base import utcnow
from app.models.international import IrCorrespondence, IrEngagement, IrGift, IrLetterTemplate
from app.models.stakeholders import Stakeholder
from app.schemas.common import Envelope, ok
from app.schemas.international import (
    CorrespondenceIn,
    CorrespondenceOut,
    CorrespondenceTransitionIn,
    DelegateIn,
    EngagementIn,
    EngagementOut,
    FollowUpIn,
    GiftIn,
    GiftOut,
    SupportIn,
    SupportStatusIn,
    TaskIn,
    TaskUpdateIn,
    TemplateIn,
    TemplateOut,
    TransitionIn,
)
from app.services import international as svc

router = APIRouter(prefix="/ir", tags=["S083 International relations"])

_READ = require_permission(P.IR_READ)
_WRITE = require_permission(P.IR_WRITE)
_CORRESPONDENCE = require_permission(P.IR_CORRESPONDENCE)
_TEMPLATES = require_permission(P.IR_TEMPLATES)
_TRANSITION = require_any_permission(P.IR_WRITE, P.IR_APPROVE)
_CORR_TRANSITION = require_any_permission(P.IR_CORRESPONDENCE, P.IR_APPROVE)

APPROVER_TARGETS = {"UNDER_REVIEW", "APPROVED", "RETURNED"}


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, mode="json")


async def _engagement(db: AsyncSession, engagement_id: str) -> IrEngagement:
    row = await db.get(IrEngagement, parse_uuid(engagement_id, label="engagement"))
    if row is None:
        raise NotFound("That engagement does not exist.", code="ENGAGEMENT_NOT_FOUND")
    return row


async def _save(db: AsyncSession, engagement: IrEngagement, identity: Identity, action: str, summary: str = "") -> dict:
    engagement.updated_at = utcnow()
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.IR_ENGAGEMENT,
        resource_id=engagement.id,
        identity=identity,
        summary=summary,
        after={"status": engagement.status, "version": engagement.version},
    )
    await db.commit()
    await db.refresh(engagement)
    return ok(engagement)


def _require_open(engagement: IrEngagement) -> None:
    if engagement.status in ("CLOSED", "CANCELLED"):
        raise Conflict("Closed or cancelled engagements cannot be changed.", code="ENGAGEMENT_CLOSED")


async def _partner(db: AsyncSession, raw: str | None):
    if not raw:
        return None
    partner_id = parse_uuid(raw, label="stakeholder")
    if await db.get(Stakeholder, partner_id) is None:
        raise ValidationFailed(
            "The partner must be an S081 stakeholder.", field_errors={"partnerStakeholderId": ["Not found in S081."]}
        )
    return partner_id


# ── Engagements ──


@router.get("/engagements", response_model=Envelope[list[EngagementOut]])
async def list_engagements(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    rows = await db.scalars(select(IrEngagement).order_by(IrEngagement.start_at.desc()))
    return ok(list(rows.all()))


@router.get("/engagements/{engagement_id}", response_model=Envelope[EngagementOut])
async def get_engagement(engagement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    return ok(await _engagement(db, engagement_id))


@router.get("/engagements/{engagement_id}/clashes", response_model=Envelope[list[EngagementOut]])
async def engagement_clashes(engagement_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    engagement = await _engagement(db, engagement_id)
    others = list((await db.scalars(select(IrEngagement))).all())
    return ok(svc.clashes(engagement, others))


@router.post("/engagements", response_model=Envelope[EngagementOut], status_code=201)
async def create_engagement(body: EngagementIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    data = body.model_dump()
    data["partner_stakeholder_id"] = await _partner(db, body.partner_stakeholder_id)
    engagement = IrEngagement(
        **data,
        reference=await svc.next_reference(db, IrEngagement, "IR"),
        owner_id=identity.sub,
        status="DRAFT",
        delegation=[],
        protocol_tasks=[],
        follow_ups=[],
        support_requests=[],
        approvals=[],
    )
    if not engagement.owner:
        engagement.owner = identity.display
    db.add(engagement)
    await db.flush()
    return await _save(db, engagement, identity, AuditAction.IR_ENGAGEMENT_CREATED)


@router.put("/engagements/{engagement_id}", response_model=Envelope[EngagementOut])
async def update_engagement(
    engagement_id: str, body: EngagementIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    data = body.model_dump()
    data["partner_stakeholder_id"] = await _partner(db, body.partner_stakeholder_id)
    material = svc.is_material_change(engagement, data)
    for key, value in data.items():
        setattr(engagement, key, value)
    engagement.version += 1
    summary = ""
    if material and engagement.status in ("APPROVED", "SCHEDULED"):
        # SRS COM-02: material changes invalidate the approval.
        engagement.status = "SUBMITTED"
        engagement.approvals = [
            *engagement.approvals,
            {
                "id": svc.item_id("apr"),
                "decision": "SUBMITTED",
                "comment": "Material change after approval; resubmitted automatically.",
                "actor": identity.display,
                "version": engagement.version,
                "occurredAt": svc.now_iso(),
            },
        ]
        summary = "Approval invalidated by a material change."
    return await _save(db, engagement, identity, AuditAction.IR_ENGAGEMENT_UPDATED, summary)


@router.post("/engagements/{engagement_id}/status", response_model=Envelope[EngagementOut])
async def transition_engagement(
    engagement_id: str, body: TransitionIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_TRANSITION)
):
    engagement = await _engagement(db, engagement_id)
    current, target = engagement.status, body.status
    if target not in svc.ENGAGEMENT_TRANSITIONS.get(current, set()):
        raise Conflict(f"An engagement cannot move from {current} to {target}.", code="INVALID_TRANSITION")
    approver_step = target in APPROVER_TARGETS or (current == "CLOSED" and target == "IN_PROGRESS")
    if approver_step and not identity.has_permission(P.IR_APPROVE):
        raise Forbidden("Only an assigned approver can take this decision.", code="APPROVER_REQUIRED")
    if not approver_step and not identity.has_permission(P.IR_WRITE):
        raise Forbidden("You cannot move this engagement.", code="PERMISSION_DENIED")
    if target == "APPROVED" and engagement.owner_id == identity.sub:
        raise Conflict("The engagement owner cannot approve their own plan.", code="FOUR_EYES")
    reopening = current == "CLOSED" and target == "IN_PROGRESS"
    if (target in svc.COMMENT_REQUIRED or reopening) and not body.comment.strip():
        raise ValidationFailed("Add a comment explaining this decision.", field_errors={"comment": ["Required."]})
    blockers = svc.engagement_blockers(engagement, target)
    if blockers:
        raise Conflict(blockers[0], code="TRANSITION_BLOCKED", extra={"blockers": blockers})
    engagement.status = target
    decision = svc.approval_decision(current, target)
    if decision:
        engagement.approvals = [
            *engagement.approvals,
            {
                "id": svc.item_id("apr"),
                "decision": decision,
                "comment": body.comment,
                "actor": identity.display,
                "version": engagement.version,
                "occurredAt": svc.now_iso(),
            },
        ]
    return await _save(
        db, engagement, identity, AuditAction.IR_ENGAGEMENT_TRANSITIONED, f"{current} → {target}. {body.comment}".strip()
    )


@router.post("/engagements/{engagement_id}/delegation", response_model=Envelope[EngagementOut])
async def add_delegate(
    engagement_id: str, body: DelegateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    engagement.delegation = [*engagement.delegation, {"id": svc.item_id("del"), **_dump(body)}]
    return await _save(db, engagement, identity, AuditAction.IR_DELEGATION_CHANGED, f"Added {body.name}.")


@router.delete("/engagements/{engagement_id}/delegation/{member_id}", response_model=Envelope[EngagementOut])
async def remove_delegate(
    engagement_id: str, member_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    if svc.find_item(engagement.delegation, member_id) is None:
        raise NotFound("That delegation member does not exist.")
    engagement.delegation = [m for m in engagement.delegation if m["id"] != member_id]
    return await _save(db, engagement, identity, AuditAction.IR_DELEGATION_CHANGED, "Removed a delegation member.")


@router.post("/engagements/{engagement_id}/protocol-tasks", response_model=Envelope[EngagementOut])
async def add_task(engagement_id: str, body: TaskIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    engagement.protocol_tasks = [
        *engagement.protocol_tasks,
        {"id": svc.item_id("tsk"), **_dump(body), "status": "OPEN", "exceptionReason": None},
    ]
    engagement.checklist_version += 1
    return await _save(db, engagement, identity, AuditAction.IR_TASK_CHANGED, f"Task added: {body.title}.")


@router.patch("/engagements/{engagement_id}/protocol-tasks/{task_id}", response_model=Envelope[EngagementOut])
async def update_task(
    engagement_id: str, task_id: str, body: TaskUpdateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    tasks = copy.deepcopy(engagement.protocol_tasks)
    task = svc.find_item(tasks, task_id)
    if task is None:
        raise NotFound("That protocol task does not exist.")
    svc.apply_task_update(task, body.status, body.evidence_ref, body.exception_reason, needs_evidence=True)
    engagement.protocol_tasks = tasks
    return await _save(db, engagement, identity, AuditAction.IR_TASK_CHANGED, f"{task['title']}: {body.status}.")


@router.post("/engagements/{engagement_id}/follow-ups", response_model=Envelope[EngagementOut])
async def add_follow_up(
    engagement_id: str, body: FollowUpIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    engagement.follow_ups = [
        *engagement.follow_ups,
        {"id": svc.item_id("fup"), **_dump(body), "status": "OPEN", "exceptionReason": None},
    ]
    return await _save(db, engagement, identity, AuditAction.IR_FOLLOW_UP_CHANGED, f"Follow-up added: {body.title}.")


@router.patch("/engagements/{engagement_id}/follow-ups/{follow_up_id}", response_model=Envelope[EngagementOut])
async def update_follow_up(
    engagement_id: str,
    follow_up_id: str,
    body: TaskUpdateIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_WRITE),
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    items = copy.deepcopy(engagement.follow_ups)
    item = svc.find_item(items, follow_up_id)
    if item is None:
        raise NotFound("That follow-up does not exist.")
    svc.apply_task_update(item, body.status, None, body.exception_reason, needs_evidence=False)
    engagement.follow_ups = items
    return await _save(db, engagement, identity, AuditAction.IR_FOLLOW_UP_CHANGED, f"{item['title']}: {body.status}.")


@router.post("/engagements/{engagement_id}/support-requests", response_model=Envelope[EngagementOut])
async def request_support(
    engagement_id: str, body: SupportIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)
):
    engagement = await _engagement(db, engagement_id)
    _require_open(engagement)
    stamp = svc.now_iso()
    request = {
        "id": svc.item_id("sup"),
        "system": body.system,
        "description": body.description,
        "externalRef": None,
        "status": "REQUESTED",
        "requestedAt": stamp,
        "updatedAt": stamp,
    }
    engagement.support_requests = [*engagement.support_requests, request]
    await enqueue(
        db,
        target_system=body.system,
        event_type="ir.support_request",
        payload={"engagementRef": engagement.reference, "description": body.description, "requestId": request["id"]},
        idempotency_key=f"s083-support:{request['id']}",
    )
    return await _save(db, engagement, identity, AuditAction.IR_SUPPORT_CHANGED, f"{body.system} requested.")


@router.patch("/engagements/{engagement_id}/support-requests/{request_id}", response_model=Envelope[EngagementOut])
async def update_support(
    engagement_id: str,
    request_id: str,
    body: SupportStatusIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_WRITE),
):
    engagement = await _engagement(db, engagement_id)
    items = copy.deepcopy(engagement.support_requests)
    item = svc.find_item(items, request_id)
    if item is None:
        raise NotFound("That support request does not exist.")
    allowed = {
        "REQUESTED": {"ACKNOWLEDGED", "FAILED"},
        "ACKNOWLEDGED": {"COMPLETED", "FAILED"},
        "FAILED": {"REQUESTED"},
        "COMPLETED": set(),
    }
    if body.status not in allowed[item["status"]]:
        raise Conflict(f"A handoff cannot move from {item['status']} to {body.status}.", code="INVALID_TRANSITION")
    if body.status == "COMPLETED" and not (body.external_ref or item.get("externalRef")):
        raise ValidationFailed(
            "Record the other system's reference before marking the handoff complete.",
            field_errors={"externalRef": ["Required."]},
        )
    item["status"], item["updatedAt"] = body.status, svc.now_iso()
    if body.external_ref:
        item["externalRef"] = body.external_ref
    engagement.support_requests = items
    return await _save(db, engagement, identity, AuditAction.IR_SUPPORT_CHANGED, f"{item['system']}: {body.status}.")


# ── Correspondence ──


async def _correspondence(db: AsyncSession, item_id: str) -> IrCorrespondence:
    row = await db.get(IrCorrespondence, parse_uuid(item_id, label="correspondence"))
    if row is None:
        raise NotFound("That correspondence does not exist.", code="CORRESPONDENCE_NOT_FOUND")
    return row


async def _link_engagement(db: AsyncSession, raw: str | None):
    if not raw:
        return None
    engagement_id = parse_uuid(raw, label="engagement")
    if await db.get(IrEngagement, engagement_id) is None:
        raise ValidationFailed("Link an existing engagement.", field_errors={"engagementId": ["Not found."]})
    return engagement_id


async def _template_version(db: AsyncSession, raw: str | None):
    if not raw:
        return None, None
    template = await db.get(IrLetterTemplate, parse_uuid(raw, label="template"))
    if template is None:
        raise ValidationFailed("Choose an existing letter template.", field_errors={"templateId": ["Not found."]})
    return template.id, template.version


def _history(item: IrCorrespondence, identity: Identity, event: str, comment: str = "") -> None:
    item.history = [
        *item.history,
        {
            "event": event,
            "actorId": identity.sub,
            "actor": identity.display,
            "comment": comment,
            "version": item.version,
            "at": svc.now_iso(),
        },
    ]


async def _save_corr(db: AsyncSession, item: IrCorrespondence, identity: Identity, action: str, summary: str = "") -> dict:
    item.updated_at = utcnow()
    await emit_audit(
        db,
        action=action,
        resource_type=ResourceType.IR_CORRESPONDENCE,
        resource_id=item.id,
        identity=identity,
        summary=summary,
        after={"status": item.status, "version": item.version},
    )
    await db.commit()
    await db.refresh(item)
    return ok(item)


@router.get("/correspondence", response_model=Envelope[list[CorrespondenceOut]])
async def list_correspondence(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    rows = await db.scalars(select(IrCorrespondence).order_by(IrCorrespondence.created_at.desc()))
    return ok(list(rows.all()))


@router.post("/correspondence", response_model=Envelope[CorrespondenceOut], status_code=201)
async def create_correspondence(
    body: CorrespondenceIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_CORRESPONDENCE)
):
    template_id, template_version = await _template_version(db, body.template_id)
    item = IrCorrespondence(
        **body.model_dump(exclude={"engagement_id", "template_id"}),
        engagement_id=await _link_engagement(db, body.engagement_id),
        template_id=template_id,
        template_version=template_version,
        reference=await svc.next_reference(db, IrCorrespondence, "COR"),
        status="RECEIVED" if body.direction == "INBOUND" else "DRAFT",
        history=[],
    )
    db.add(item)
    await db.flush()
    _history(item, identity, "CREATED")
    return await _save_corr(db, item, identity, AuditAction.IR_CORRESPONDENCE_CREATED)


@router.put("/correspondence/{item_id}", response_model=Envelope[CorrespondenceOut])
async def update_correspondence(
    item_id: str, body: CorrespondenceIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_CORRESPONDENCE)
):
    item = await _correspondence(db, item_id)
    if item.status in ("DISPATCHED", "CLOSED", "RESPONDED"):
        raise Conflict("Sent or closed correspondence cannot be edited.", code="CORRESPONDENCE_LOCKED")
    if body.direction != item.direction:
        raise ValidationFailed("The direction of a registered item cannot change.")
    material = any(getattr(item, f) != getattr(body, f) for f in ("body", "subject", "recipient", "language"))
    template_id, template_version = await _template_version(db, body.template_id)
    for key, value in body.model_dump(exclude={"engagement_id", "template_id"}).items():
        setattr(item, key, value)
    item.engagement_id = await _link_engagement(db, body.engagement_id)
    if template_id != item.template_id:
        item.template_id, item.template_version = template_id, template_version
    summary = ""
    if material:
        item.version += 1
        if item.direction == "OUTBOUND" and item.status in ("APPROVED", "IN_REVIEW"):
            item.status = "DRAFT"  # unapproved text can never be dispatched
            summary = "Material change: approval invalidated."
    _history(item, identity, "UPDATED", summary)
    return await _save_corr(db, item, identity, AuditAction.IR_CORRESPONDENCE_UPDATED, summary)


@router.post("/correspondence/{item_id}/status", response_model=Envelope[CorrespondenceOut])
async def transition_correspondence(
    item_id: str,
    body: CorrespondenceTransitionIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(_CORR_TRANSITION),
):
    item = await _correspondence(db, item_id)
    current, target = item.status, body.status
    if target not in svc.correspondence_transitions(item):
        raise Conflict(f"Correspondence cannot move from {current} to {target}.", code="INVALID_TRANSITION")
    deciding = current == "IN_REVIEW" and target in ("APPROVED", "RETURNED")
    if deciding and not identity.has_permission(P.IR_APPROVE):
        raise Forbidden("Only an assigned approver can approve or return letters.", code="APPROVER_REQUIRED")
    if not deciding and not identity.has_permission(P.IR_CORRESPONDENCE):
        raise Forbidden("You cannot move this correspondence.", code="PERMISSION_DENIED")
    if target == "RETURNED" and not body.comment.strip():
        raise ValidationFailed("Say what needs to change.", field_errors={"comment": ["Required."]})
    if target == "APPROVED":
        author = item.history[0]["actorId"] if item.history else ""
        if author == identity.sub:
            raise Conflict("Someone other than the drafter must approve this letter.", code="FOUR_EYES")
        item.approved_version, item.approved_by_id = item.version, identity.sub
    if target == "DISPATCHED":
        if item.approved_version != item.version:
            raise Conflict("Only the approved version can be dispatched.", code="UNAPPROVED_TEXT")
        message = await enqueue(
            db,
            target_system="S074",
            event_type="ir.letter_dispatch",
            payload={
                "reference": item.reference,
                "recipient": item.recipient,
                "subject": item.subject,
                "language": item.language,
                "classification": item.classification,
                "documentRef": item.document_ref,
            },
            idempotency_key=f"s083-dispatch:{item.id}:{item.version}",
        )
        item.dispatch_ref = f"S074-OUTBOX-{message.id.hex[:12].upper()}"
        item.sent_at = utcnow()
    item.status = target
    _history(item, identity, target, body.comment)
    return await _save_corr(db, item, identity, AuditAction.IR_CORRESPONDENCE_TRANSITIONED, f"{current} → {target}")


# ── Letter templates ──


@router.get("/letter-templates", response_model=Envelope[list[TemplateOut]])
async def list_templates(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    rows = await db.scalars(
        select(IrLetterTemplate).order_by(IrLetterTemplate.name, IrLetterTemplate.language, IrLetterTemplate.version.desc())
    )
    return ok(list(rows.all()))


@router.post("/letter-templates", response_model=Envelope[TemplateOut], status_code=201)
async def create_template(body: TemplateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_TEMPLATES)):
    exists = await db.scalar(
        select(IrLetterTemplate).where(
            func.lower(IrLetterTemplate.name) == body.name.lower(),
            IrLetterTemplate.language == body.language,
            IrLetterTemplate.active.is_(True),
        )
    )
    if exists is not None:
        raise Conflict(
            "A template with that name already exists in this language; save a new version instead.", code="DUPLICATE_TEMPLATE"
        )
    template = IrLetterTemplate(**body.model_dump(), version=1, active=True)
    db.add(template)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.IR_TEMPLATE_SAVED,
        resource_type=ResourceType.IR_TEMPLATE,
        resource_id=template.id,
        identity=identity,
        after={"name": body.name, "language": body.language, "version": 1},
    )
    await db.commit()
    await db.refresh(template)
    return ok(template)


@router.put("/letter-templates/{template_id}", response_model=Envelope[TemplateOut])
async def new_template_version(
    template_id: str, body: TemplateIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_TEMPLATES)
):
    current = await db.get(IrLetterTemplate, parse_uuid(template_id, label="template"))
    if current is None:
        raise NotFound("That template does not exist.")
    if not current.active:
        raise Conflict("Only the active version can be revised.", code="TEMPLATE_SUPERSEDED")
    current.active = False
    successor = IrLetterTemplate(**body.model_dump(), version=current.version + 1, active=True)
    db.add(successor)
    await db.flush()
    await emit_audit(
        db,
        action=AuditAction.IR_TEMPLATE_SAVED,
        resource_type=ResourceType.IR_TEMPLATE,
        resource_id=successor.id,
        identity=identity,
        after={"name": body.name, "language": body.language, "version": successor.version},
    )
    await db.commit()
    await db.refresh(successor)
    return ok(successor)


# ── Gifts ──


@router.get("/gifts", response_model=Envelope[list[GiftOut]])
async def list_gifts(db: AsyncSession = Depends(get_db), identity: Identity = Depends(_READ)):
    rows = await db.scalars(select(IrGift).order_by(IrGift.gift_date.desc()))
    return ok(list(rows.all()))


@router.post("/gifts", response_model=Envelope[GiftOut], status_code=201)
async def record_gift(body: GiftIn, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    gift = IrGift(
        **body.model_dump(exclude={"engagement_id"}),
        engagement_id=await _link_engagement(db, body.engagement_id),
        s011_status="PENDING" if body.direction == "RECEIVED" else "NOT_REQUIRED",
        recorded_by=identity.sub,
    )
    db.add(gift)
    await db.flush()
    if body.direction == "RECEIVED":
        gift.flag_attempts = 1
        await enqueue(
            db,
            target_system="S011",
            event_type="ir.gift_received",
            payload={
                "giftId": str(gift.id),
                "giver": gift.giver,
                "recipient": gift.recipient,
                "description": gift.description,
                "date": gift.gift_date,
                "value": gift.value,
                "currency": gift.currency,
            },
            idempotency_key=f"s011-gift:{gift.id}",
        )
    await emit_audit(
        db,
        action=AuditAction.IR_GIFT_RECORDED,
        resource_type=ResourceType.IR_GIFT,
        resource_id=gift.id,
        identity=identity,
        after={"direction": body.direction, "s011Status": gift.s011_status},
    )
    await db.commit()
    await db.refresh(gift)
    return ok(gift)


@router.post("/gifts/{gift_id}/s011-flag", response_model=Envelope[GiftOut])
async def retry_gift_flag(gift_id: str, db: AsyncSession = Depends(get_db), identity: Identity = Depends(_WRITE)):
    gift = await db.get(IrGift, parse_uuid(gift_id, label="gift"))
    if gift is None:
        raise NotFound("That gift does not exist.")
    if gift.direction != "RECEIVED":
        raise Conflict("Only gifts received are cross-flagged to S011.", code="FLAG_NOT_REQUIRED")
    if gift.s011_status == "ACKNOWLEDGED":
        raise Conflict("S011 has already acknowledged this gift.", code="ALREADY_ACKNOWLEDGED")
    # Same idempotency key: the retry re-queues the one flag, never a second one.
    message = await db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == f"s011-gift:{gift.id}"))
    if message is None:
        message = await enqueue(
            db,
            target_system="S011",
            event_type="ir.gift_received",
            payload={"giftId": str(gift.id), "giver": gift.giver, "recipient": gift.recipient},
            idempotency_key=f"s011-gift:{gift.id}",
        )
    message.status, message.next_attempt_at = OutboxStatus.PENDING, utcnow()
    gift.flag_attempts += 1
    gift.s011_status = "PENDING"
    await emit_audit(
        db,
        action=AuditAction.IR_GIFT_FLAG_RETRIED,
        resource_type=ResourceType.IR_GIFT,
        resource_id=gift.id,
        identity=identity,
        after={"attempts": gift.flag_attempts},
    )
    await db.commit()
    await db.refresh(gift)
    return ok(gift)
