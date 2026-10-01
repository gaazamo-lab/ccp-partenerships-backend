"""
S088_consult Public-Survey / Consultation Platform.

Question sets, triggers and the theme codebook are versionless JSON documents on
the consultation (they are edited as a whole in the builder). Responses keep
personal data in `respondent` only when the respondent consented to the link
(PRD AC-15); otherwise it is never stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class ConsultationStatus:
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    ALL = [DRAFT, REVIEW, SCHEDULED, OPEN, CLOSED, ARCHIVED]
    PUBLIC = [SCHEDULED, OPEN, CLOSED]
    EDITABLE = [DRAFT, REVIEW]


class Consultation(Base):
    __tablename__ = "con_consultation"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ConsultationStatus.DRAFT, index=True)
    languages: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    anonymous_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    collect_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audience_source: Mapped[str] = mapped_column(String(16), nullable=False, default="PUBLIC")
    audience_segment_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    invited_count: Mapped[int | None] = mapped_column(Integer)
    questions: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    triggers: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    themes: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    outcome_summary: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ConsultationResponse(Base):
    __tablename__ = "con_response"

    id: Mapped[uuid.UUID] = uuid_pk()
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("con_consultation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submitted_at: Mapped[datetime] = created_at_column()
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    answers: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    consent_to_identity_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    respondent: Mapped[dict | None] = mapped_column(JSONType)
    themes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)


class ConsultationInvitation(Base):
    __tablename__ = "con_invitation"

    id: Mapped[uuid.UUID] = uuid_pk()
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("con_consultation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    segment_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    communication_ref: Mapped[str | None] = mapped_column(String(128))
    sent_by: Mapped[str] = mapped_column(String(200), nullable=False)
    sent_at: Mapped[datetime] = created_at_column()
