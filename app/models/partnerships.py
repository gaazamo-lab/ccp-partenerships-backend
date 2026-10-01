"""
S082 MOU & Partnership Lifecycle Tracker.

Agreements reference S081 stakeholders by ID (never copying their data), S136
legal records and S003 signed documents by reference. `version` backs the
ETag / If-Match optimistic-concurrency contract.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class PartnershipStatus:
    DRAFT = "DRAFT"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    SIGNATURE_PENDING = "SIGNATURE_PENDING"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    ALL = [DRAFT, LEGAL_REVIEW, SIGNATURE_PENDING, ACTIVE, RENEWAL_DUE, EXPIRED, TERMINATED]


class AgreementType:
    ALL = ["MOU", "PARTNERSHIP_AGREEMENT", "COOPERATION_FRAMEWORK"]


class ObligationStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"
    ALL = [NOT_STARTED, IN_PROGRESS, COMPLETED, OVERDUE, WAIVED]
    CLOSED = [COMPLETED, WAIVED]


class RenewalAlertStatus:
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    OPEN = [SCHEDULED, DUE, SENT, FAILED]


class ReviewOutcome:
    ALL = ["EXCEEDS_EXPECTATIONS", "ON_TRACK", "NEEDS_ATTENTION", "NO_LONGER_STRATEGIC"]


class RenewalRecommendation:
    ALL = ["RENEW", "RENEW_WITH_CHANGES", "TERMINATE", "DEFER"]


class PartnershipAgreement(Base):
    __tablename__ = "mou_agreement"

    id: Mapped[uuid.UUID] = uuid_pk()
    stakeholder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("crm_stakeholder.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    party_stakeholder_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    agreement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PartnershipStatus.DRAFT, index=True)
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    effective_date: Mapped[dt.date | None] = mapped_column(Date)
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    value_commitment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deliverables: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    legal_contract_ref: Mapped[str | None] = mapped_column(String(120))
    signed_document_ref: Mapped[str | None] = mapped_column(String(120))
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # {terminatedAt, reason, documentationRef, finalArchiveRef, approvedBy}
    termination: Mapped[dict | None] = mapped_column(JSONType)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    obligations: Mapped[list[PartnershipObligation]] = relationship(
        back_populates="agreement", cascade="all, delete-orphan", lazy="selectin"
    )


class PartnershipObligation(Base):
    __tablename__ = "mou_obligation"

    id: Mapped[uuid.UUID] = uuid_pk()
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_agreement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(160), nullable=False)
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ObligationStatus.NOT_STARTED)
    evidence_references: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    reminder_lead_days: Mapped[int | None] = mapped_column(Integer)
    escalation_owner: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    agreement: Mapped[PartnershipAgreement] = relationship(back_populates="obligations")


class ObligationProgressNote(Base):
    __tablename__ = "mou_obligation_progress"

    id: Mapped[uuid.UUID] = uuid_pk()
    obligation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_obligation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class PartnershipReview(Base):
    __tablename__ = "mou_review"

    id: Mapped[uuid.UUID] = uuid_pk()
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_agreement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    outputs: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    strategic_score: Mapped[int] = mapped_column(Integer, nullable=False)
    issues: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    recommendations: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    renewal_recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    next_review_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class PartnershipRenewal(Base):
    __tablename__ = "mou_renewal"

    id: Mapped[uuid.UUID] = uuid_pk()
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_agreement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_effective_date: Mapped[dt.date | None] = mapped_column(Date)
    previous_expiry_date: Mapped[dt.date | None] = mapped_column(Date)
    previous_legal_contract_ref: Mapped[str | None] = mapped_column(String(120))
    previous_signed_document_ref: Mapped[str | None] = mapped_column(String(120))
    effective_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    legal_contract_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    signed_document_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    terms_summary: Mapped[str] = mapped_column(Text, nullable=False)
    renewed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    renewed_at: Mapped[datetime] = created_at_column()


class PartnershipRenewalAlert(Base):
    __tablename__ = "mou_renewal_alert"

    id: Mapped[uuid.UUID] = uuid_pk()
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_agreement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_days: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    recipients: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RenewalAlertStatus.SCHEDULED)
    communication_ref: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class PartnershipHistory(Base):
    __tablename__ = "mou_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mou_agreement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = created_at_column()
