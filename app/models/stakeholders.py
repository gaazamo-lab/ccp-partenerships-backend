"""
S081 Stakeholder / Partner CRM: organisations, contacts, engagement history and
audience segments.

String-valued enums are plain constant classes (stored as `String`), matching the
display values in `packages/types/src/stakeholders.ts`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class StakeholderCategory:
    ALL = [
        "Donor",
        "Embassy",
        "Government",
        "International body",
        "Judiciary",
        "Media",
        "Peer institution",
        "Professional body",
        "University",
    ]
    REGULATED = ["Donor", "Embassy", "International body"]


class RelationshipStatus:
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    MOU_LINKED = "MOU linked"
    SCREENING_PENDING = "Screening pending"
    ALL = [ACTIVE, INACTIVE, MOU_LINKED, SCREENING_PENDING]


class HealthLevel:
    ALL = ["At risk", "Healthy", "Strong"]


class PipelineStage:
    ALL = ["Prospect", "Engaged", "Negotiation", "MOU", "Dormant"]


class ScreeningStatus:
    CLEARED = "Cleared"
    NOT_REQUIRED = "Not required"
    PENDING = "Pending"
    REVIEW_REQUIRED = "Review required"
    REJECTED = "Rejected"
    ALL = [CLEARED, NOT_REQUIRED, PENDING, REVIEW_REQUIRED, REJECTED]
    BLOCKING = [PENDING, REVIEW_REQUIRED, REJECTED]
    DECISIONS = [CLEARED, REVIEW_REQUIRED, REJECTED]


class ConsentStatus:
    CONSENTED = "Consented"
    ALL = ["Consented", "Expired", "Not recorded", "Withdrawn"]
    CHANNELS = ["Email", "Form", "In person", "Letter", "Phone"]


class EngagementType:
    ALL = ["Call", "Campaign", "Correspondence", "Email", "Event", "Meeting", "MOU"]


class Stakeholder(Base):
    __tablename__ = "crm_stakeholder"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RelationshipStatus.ACTIVE)
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="Healthy")
    pipeline_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="Prospect")
    location: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duplicate_override_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    contacts: Mapped[list[StakeholderContact]] = relationship(
        back_populates="stakeholder",
        cascade="all, delete-orphan",
        order_by="StakeholderContact.created_at",
        lazy="selectin",
    )
    engagements: Mapped[list[StakeholderEngagement]] = relationship(
        back_populates="stakeholder",
        cascade="all, delete-orphan",
        order_by="(StakeholderEngagement.date.desc(), StakeholderEngagement.created_at.desc())",
        lazy="selectin",
    )


class StakeholderContact(Base):
    __tablename__ = "crm_stakeholder_contact"

    id: Mapped[uuid.UUID] = uuid_pk()
    stakeholder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("crm_stakeholder.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    consent: Mapped[str] = mapped_column(String(16), nullable=False, default="Not recorded")
    consent_date: Mapped[dt.date | None] = mapped_column(Date)
    consent_channel: Mapped[str | None] = mapped_column(String(16))
    screening: Mapped[str] = mapped_column(String(24), nullable=False, default=ScreeningStatus.NOT_REQUIRED)
    # {outcome, reviewer, reviewedAt, notes, caseRef} — the latest S203 decision.
    screening_record: Mapped[dict | None] = mapped_column(JSONType)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    stakeholder: Mapped[Stakeholder] = relationship(back_populates="contacts")


class StakeholderEngagement(Base):
    __tablename__ = "crm_stakeholder_engagement"

    id: Mapped[uuid.UUID] = uuid_pk()
    stakeholder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("crm_stakeholder.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="Partner CRM")
    logged_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()

    stakeholder: Mapped[Stakeholder] = relationship(back_populates="engagements")


class Segment(Base):
    __tablename__ = "crm_segment"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {categories: [], statuses: [], owners: [], consentedOnly: bool}
    criteria: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    used_by: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
