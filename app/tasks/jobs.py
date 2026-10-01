"""
Background jobs. Each job is a plain function taking a sync `Session` (unit
testable) plus a thin Celery task wrapper that opens the session.

- `relay_outbox`: delivers pending outbox rows to S074 / S203 / S204 / S011 / S225 /
  S084 / S078 / S086 with exponential backoff. Targets without a configured URL
  are left pending — business records never depend on delivery.
- `partnership_sweep`: ACTIVE → RENEWAL_DUE inside 90 days, → EXPIRED after the
  expiry date; queues due renewal alerts through S074.
- `consultation_sweep`: opens scheduled consultations at `opensAt` and closes
  open ones at `closesAt`.
- `correspondence_sweep`: queues S074 escalations for overdue correspondence.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

import httpx
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SyncSessionFactory
from app.models.audit import OutboxEvent, OutboxStatus
from app.models.consultations import Consultation
from app.models.international import IrCorrespondence, IrGift
from app.models.partnerships import (
    PartnershipAgreement,
    PartnershipHistory,
    PartnershipRenewalAlert,
    PartnershipStatus,
    RenewalAlertStatus,
)

logger = logging.getLogger(__name__)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _target_url(target: str) -> str:
    settings = get_settings()
    return {
        "S074": settings.S074_COMMS_URL,
        "S203": settings.S203_SCREENING_URL,
        "S204": settings.S204_AUDIT_URL,
        "S011": settings.S011_GIFTS_URL,
        "S225": settings.S225_ANALYTICS_URL,
    }.get(target, "")


def _queue(session: Session, *, target: str, event_type: str, payload: dict[str, Any], key: str) -> None:
    if session.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == key)) is None:
        session.add(
            OutboxEvent(
                target_system=target,
                event_type=event_type,
                payload=payload,
                idempotency_key=key,
                status=OutboxStatus.PENDING,
                next_attempt_at=_now(),
            )
        )


def _after_delivery(session: Session, row: OutboxEvent) -> None:
    """Reflect acknowledgements back onto business records."""
    if row.target_system == "S011" and row.event_type == "ir.gift_received":
        gift = session.get(IrGift, uuid.UUID(row.payload["giftId"]))
        if gift is not None:
            gift.s011_status, gift.s011_ref = "ACKNOWLEDGED", row.external_ref


def relay_outbox(session: Session, client: httpx.Client, limit: int = 100) -> dict[str, int]:
    settings = get_settings()
    now = _now()
    rows = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    for row in rows:
        if row.next_attempt_at and _aware(row.next_attempt_at) > now:
            continue
        url = _target_url(row.target_system)
        if not url:
            counts["skipped"] += 1
            continue
        try:
            response = client.post(
                url,
                json={"eventType": row.event_type, "idempotencyKey": row.idempotency_key, "payload": row.payload},
                headers={
                    "Idempotency-Key": row.idempotency_key,
                    "X-Api-Key": settings.S074_API_KEY if row.target_system == "S074" else settings.S203_API_KEY,
                }
                if row.target_system in {"S074", "S203"}
                else {"Idempotency-Key": row.idempotency_key},
                timeout=settings.INTEGRATION_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            row.status, row.sent_at = OutboxStatus.SENT, now
            row.external_ref = str(body.get("id") or body.get("reference") or "")[:128] or None
            _after_delivery(session, row)
            counts["sent"] += 1
        except Exception as exc:  # noqa: BLE001 — every delivery failure is retried or parked
            row.attempts += 1
            row.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if row.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED
                if row.target_system == "S011":
                    gift = session.get(IrGift, uuid.UUID(row.payload["giftId"]))
                    if gift is not None:
                        gift.s011_status = "FAILED"
            else:
                row.next_attempt_at = now + dt.timedelta(seconds=min(3600, 30 * 2**row.attempts))
            counts["failed"] += 1
            logger.warning(
                "outbox.delivery_failed target=%s key=%s attempts=%s", row.target_system, row.idempotency_key, row.attempts
            )
    session.commit()
    return counts


def partnership_sweep(session: Session, today: dt.date | None = None) -> dict[str, int]:
    today = today or dt.date.today()
    counts = {"renewal_due": 0, "expired": 0, "alerts": 0}
    agreements = session.scalars(
        select(PartnershipAgreement).where(
            PartnershipAgreement.status.in_([PartnershipStatus.ACTIVE, PartnershipStatus.RENEWAL_DUE])
        )
    ).all()
    for agreement in agreements:
        if agreement.expiry_date is None:
            continue
        if agreement.expiry_date < today:
            agreement.status = PartnershipStatus.EXPIRED
            session.add(
                PartnershipHistory(
                    agreement_id=agreement.id,
                    action="EXPIRED",
                    summary="Expired automatically after the expiry date.",
                    actor="System",
                )
            )
            counts["expired"] += 1
        elif agreement.status == PartnershipStatus.ACTIVE and agreement.expiry_date <= today + dt.timedelta(days=90):
            agreement.status = PartnershipStatus.RENEWAL_DUE
            session.add(
                PartnershipHistory(
                    agreement_id=agreement.id,
                    action="STATUS_CHANGED",
                    summary="Renewal due: within 90 days of expiry.",
                    actor="System",
                )
            )
            counts["renewal_due"] += 1
    due = session.scalars(
        select(PartnershipRenewalAlert).where(
            PartnershipRenewalAlert.status == RenewalAlertStatus.SCHEDULED, PartnershipRenewalAlert.scheduled_for <= today
        )
    ).all()
    for alert in due:
        agreement = session.get(PartnershipAgreement, alert.agreement_id)
        if agreement is None or agreement.status in (PartnershipStatus.TERMINATED, PartnershipStatus.EXPIRED):
            alert.status = RenewalAlertStatus.CANCELLED
            continue
        key = f"s082-alert:{alert.id}:first"
        _queue(
            session,
            target="S074",
            event_type="partnership.renewal_alert",
            key=key,
            payload={
                "recipients": alert.recipients,
                "template": "s082-renewal-alert",
                "placeholders": {
                    "reference": agreement.reference,
                    "title": agreement.title,
                    "expiryDate": agreement.expiry_date.isoformat(),
                    "milestoneDays": alert.milestone_days,
                },
            },
        )
        alert.status, alert.sent_at = RenewalAlertStatus.SENT, _now()
        alert.communication_ref = "S074-AUTO"
        session.add(
            PartnershipHistory(
                agreement_id=agreement.id,
                action="RENEWAL_ALERT_UPDATED",
                summary=f"{alert.milestone_days}-day renewal alert dispatched automatically.",
                actor="System",
            )
        )
        counts["alerts"] += 1
    session.commit()
    return counts


def consultation_sweep(session: Session) -> dict[str, int]:
    now = _now()
    counts = {"opened": 0, "closed": 0}
    for consultation in session.scalars(select(Consultation).where(Consultation.status.in_(["SCHEDULED", "OPEN"]))).all():
        if consultation.status == "SCHEDULED" and _aware(consultation.opens_at) <= now < _aware(consultation.closes_at):
            consultation.status = "OPEN"
            counts["opened"] += 1
        elif consultation.status == "OPEN" and _aware(consultation.closes_at) <= now:
            consultation.status = "CLOSED"
            counts["closed"] += 1
    session.commit()
    return counts


def correspondence_sweep(session: Session, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    overdue = session.scalars(
        select(IrCorrespondence).where(
            IrCorrespondence.status.in_(["RECEIVED", "AWAITING_RESPONSE"]), IrCorrespondence.response_deadline < today
        )
    ).all()
    for item in overdue:
        _queue(
            session,
            target="S074",
            event_type="ir.correspondence_overdue",
            key=f"s083-overdue:{item.id}:{today.isoformat()}",
            payload={
                "reference": item.reference,
                "owner": item.owner,
                "subject": item.subject,
                "deadline": item.response_deadline.isoformat() if item.response_deadline else None,
            },
        )
    session.commit()
    return len(overdue)


@shared_task(name="pcrm.relay_outbox")
def relay_outbox_task() -> dict[str, int]:
    with SyncSessionFactory() as session, httpx.Client() as client:
        return relay_outbox(session, client)


@shared_task(name="pcrm.partnership_sweep")
def partnership_sweep_task() -> dict[str, int]:
    with SyncSessionFactory() as session:
        return partnership_sweep(session)


@shared_task(name="pcrm.consultation_sweep")
def consultation_sweep_task() -> dict[str, int]:
    with SyncSessionFactory() as session:
        return consultation_sweep(session)


@shared_task(name="pcrm.correspondence_sweep")
def correspondence_sweep_task() -> int:
    with SyncSessionFactory() as session:
        return correspondence_sweep(session)
