"""
S082 lifecycle rules. The frontend enforces the same guards
(`features/partnerships/lifecycle.ts`); the server repeats every one of them
transactionally because disabled buttons are only a usability aid.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.base import utcnow
from app.models.partnerships import (
    ObligationStatus,
    PartnershipAgreement,
    PartnershipHistory,
    PartnershipObligation,
    PartnershipRenewalAlert,
    PartnershipStatus,
    RenewalAlertStatus,
)
from app.models.stakeholders import (
    RelationshipStatus,
    ScreeningStatus,
    Stakeholder,
    StakeholderEngagement,
)

S = PartnershipStatus

# Manual transitions via POST /partnerships/:id/status. Renewal and termination
# have their own endpoints because they carry evidence.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.DRAFT: {S.LEGAL_REVIEW},
    S.LEGAL_REVIEW: {S.SIGNATURE_PENDING, S.DRAFT},
    S.SIGNATURE_PENDING: {S.ACTIVE, S.LEGAL_REVIEW},
    S.ACTIVE: {S.RENEWAL_DUE, S.EXPIRED},
    S.RENEWAL_DUE: {S.EXPIRED},
    S.EXPIRED: set(),
    S.TERMINATED: set(),
}

RENEWAL_MILESTONES = (180, 90, 30)


def effective_obligation_status(obligation: PartnershipObligation, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if obligation.status in ObligationStatus.CLOSED:
        return obligation.status
    return ObligationStatus.OVERDUE if obligation.due_date < today else obligation.status


def effective_alert_status(alert: PartnershipRenewalAlert, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if alert.status == RenewalAlertStatus.SCHEDULED and alert.scheduled_for <= today:
        return RenewalAlertStatus.DUE
    return alert.status


async def party_blockers(db: AsyncSession, party_ids: list[str]) -> list[str]:
    blockers: list[str] = []
    for raw in party_ids:
        party = await db.get(Stakeholder, uuid.UUID(str(raw)))
        if party is None:
            blockers.append(f"Party {raw} is not an S081 stakeholder.")
            continue
        if party.status == RelationshipStatus.INACTIVE:
            blockers.append(f"{party.name} is inactive in S081.")
        elif any(c.active and c.screening in ScreeningStatus.BLOCKING for c in party.contacts):
            blockers.append(f"{party.name} must clear S203 screening.")
    return blockers


async def transition_blockers(db: AsyncSession, agreement: PartnershipAgreement, target: str) -> list[str]:
    blockers: list[str] = []
    if target in (S.LEGAL_REVIEW, S.SIGNATURE_PENDING, S.ACTIVE) and not agreement.legal_contract_ref:
        blockers.append("Link the S136 legal record.")
    if target == S.ACTIVE:
        if not agreement.signed_document_ref:
            blockers.append("Link the executed S003 document.")
        if not agreement.effective_date:
            blockers.append("Set the effective date.")
        if not agreement.expiry_date:
            blockers.append("Set the expiry date.")
        if not agreement.obligations:
            blockers.append("Define at least one agreement obligation.")
        if not agreement.deliverables:
            blockers.append("List at least one deliverable.")
        blockers.extend(await party_blockers(db, agreement.party_stakeholder_ids))
    if target == S.EXPIRED and (not agreement.expiry_date or agreement.expiry_date >= dt.date.today()):
        blockers.append("An agreement can only expire after its expiry date.")
    return blockers


def termination_blockers(agreement: PartnershipAgreement) -> list[str]:
    open_items = [o for o in agreement.obligations if o.status not in ObligationStatus.CLOSED]
    if open_items:
        plural = "" if len(open_items) == 1 else "s"
        return [f"Close or waive {len(open_items)} outstanding obligation{plural}."]
    return []


async def next_reference(db: AsyncSession, year: int) -> str:
    prefix = f"CLET/MOU/{year}/"
    count = await db.scalar(
        select(func.count()).select_from(PartnershipAgreement).where(PartnershipAgreement.reference.like(f"{prefix}%"))
    )
    sequence = int(count or 0) + 1
    while True:
        reference = f"{prefix}{sequence:03d}"
        if not await db.scalar(select(PartnershipAgreement.id).where(PartnershipAgreement.reference == reference)):
            return reference
        sequence += 1


async def load_agreement(db: AsyncSession, agreement_id: uuid.UUID) -> PartnershipAgreement:
    row = await db.scalar(
        select(PartnershipAgreement).where(PartnershipAgreement.id == agreement_id).execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFound("That agreement does not exist.", code="AGREEMENT_NOT_FOUND")
    return row


def check_version(agreement: PartnershipAgreement, if_match: str | None) -> None:
    """Honour `If-Match` when the client sends it (S082 optimistic-concurrency contract)."""
    if if_match is None:
        return
    expected = if_match.strip().strip('"').removeprefix("W/").strip('"')
    if expected != str(agreement.version):
        raise Conflict(
            "Someone else changed this agreement. Reload it and try again.",
            code="STALE_WRITE",
            extra={"currentVersion": agreement.version},
        )


def add_history(db: AsyncSession, agreement_id: uuid.UUID, action: str, summary: str, actor: str) -> None:
    db.add(PartnershipHistory(agreement_id=agreement_id, action=action, summary=summary, actor=actor))


async def validate_parties(db: AsyncSession, stakeholder_id: uuid.UUID, party_ids: list[uuid.UUID]) -> list[str]:
    ids = [stakeholder_id, *[p for p in party_ids if p != stakeholder_id]]
    for item in ids:
        if await db.get(Stakeholder, item) is None:
            raise ValidationFailed(
                "Every party must be an existing S081 stakeholder.",
                field_errors={"partyStakeholderIds": [f"{item} does not exist in S081."]},
            )
    return [str(item) for item in ids]


def build_renewal_alerts(
    agreement: PartnershipAgreement, recipients: list[str], today: dt.date | None = None
) -> list[PartnershipRenewalAlert]:
    today = today or dt.date.today()
    if agreement.expiry_date is None:
        return []
    alerts = []
    for milestone in RENEWAL_MILESTONES:
        scheduled = agreement.expiry_date - dt.timedelta(days=milestone)
        alerts.append(
            PartnershipRenewalAlert(
                agreement_id=agreement.id,
                milestone_days=milestone,
                scheduled_for=scheduled,
                recipients=list(recipients),
                status=RenewalAlertStatus.DUE if scheduled <= today else RenewalAlertStatus.SCHEDULED,
            )
        )
    return alerts


async def open_alerts(db: AsyncSession, agreement_id: uuid.UUID) -> list[PartnershipRenewalAlert]:
    rows = await db.scalars(
        select(PartnershipRenewalAlert).where(
            PartnershipRenewalAlert.agreement_id == agreement_id,
            PartnershipRenewalAlert.status.in_(RenewalAlertStatus.OPEN),
        )
    )
    return list(rows.all())


async def cancel_open_alerts(db: AsyncSession, agreement_id: uuid.UUID) -> list[str]:
    """Cancel open alerts and return the recipients they were addressed to."""
    recipients: list[str] = []
    for alert in await open_alerts(db, agreement_id):
        recipients = recipients or list(alert.recipients)
        alert.status = RenewalAlertStatus.CANCELLED
    return recipients


async def link_stakeholders_on_activation(db: AsyncSession, agreement: PartnershipAgreement) -> None:
    """S081 integration: parties of an active agreement show as MOU linked, with a timeline entry."""
    for raw in agreement.party_stakeholder_ids:
        party = await db.get(Stakeholder, uuid.UUID(str(raw)))
        if party is None:
            continue
        if party.status in (RelationshipStatus.ACTIVE, RelationshipStatus.MOU_LINKED):
            party.status = RelationshipStatus.MOU_LINKED
        party.pipeline_stage = "MOU"
        db.add(
            StakeholderEngagement(
                stakeholder_id=party.id,
                type="MOU",
                title=f"{agreement.reference} activated",
                summary=agreement.title,
                date=dt.date.today(),
                source="S082 MOU Tracker",
            )
        )


def serialize_agreement(agreement: PartnershipAgreement) -> dict:
    return {
        "id": agreement.id,
        "stakeholder_id": agreement.stakeholder_id,
        "party_stakeholder_ids": [str(p) for p in agreement.party_stakeholder_ids],
        "reference": agreement.reference,
        "title": agreement.title,
        "agreement_type": agreement.agreement_type,
        "status": agreement.status,
        "owner": agreement.owner,
        "effective_date": agreement.effective_date,
        "expiry_date": agreement.expiry_date,
        "value_commitment": agreement.value_commitment,
        "deliverables": list(agreement.deliverables),
        "legal_contract_ref": agreement.legal_contract_ref,
        "signed_document_ref": agreement.signed_document_ref,
        "renewal_count": agreement.renewal_count,
        "termination": agreement.termination,
        "created_at": agreement.created_at,
        "updated_at": agreement.updated_at,
    }


def serialize_obligation(obligation: PartnershipObligation) -> dict:
    return {
        "id": obligation.id,
        "agreement_id": obligation.agreement_id,
        "title": obligation.title,
        "description": obligation.description,
        "owner": obligation.owner,
        "due_date": obligation.due_date,
        "status": effective_obligation_status(obligation),
        "evidence_references": list(obligation.evidence_references),
        "reminder_lead_days": obligation.reminder_lead_days,
        "escalation_owner": obligation.escalation_owner,
        "updated_at": obligation.updated_at,
    }


def serialize_alert(alert: PartnershipRenewalAlert) -> dict:
    return {
        "id": alert.id,
        "agreement_id": alert.agreement_id,
        "milestone_days": alert.milestone_days,
        "scheduled_for": alert.scheduled_for,
        "recipients": list(alert.recipients),
        "status": effective_alert_status(alert),
        "communication_ref": alert.communication_ref,
        "sent_at": alert.sent_at,
        "acknowledged_at": alert.acknowledged_at,
        "acknowledged_by": alert.acknowledged_by,
    }


def touch(agreement: PartnershipAgreement) -> None:
    agreement.version += 1
    agreement.updated_at = utcnow()
