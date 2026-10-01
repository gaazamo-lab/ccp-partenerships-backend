"""
S083 International Relations & Protocols Workspace.

An engagement is one aggregate: its delegation, protocol tasks, follow-ups,
support handoffs and approval history are JSON arrays of items with stable IDs,
always changed through the engagement endpoints and guarded by `version`.
Partner identities stay in S081, travel in S084, events in S078.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class IrEngagement(Base):
    __tablename__ = "ir_engagement"

    id: Mapped[uuid.UUID] = uuid_pk()
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    partner_stakeholder_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("crm_stakeholder.id", ondelete="SET NULL"))
    partner_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    host: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    venue: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Accra")
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="INTERNAL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT", index=True)
    checklist_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agenda_ref: Mapped[str | None] = mapped_column(String(120))
    briefing_pack_ref: Mapped[str | None] = mapped_column(String(120))
    minutes_ref: Mapped[str | None] = mapped_column(String(120))
    final_report_ref: Mapped[str | None] = mapped_column(String(120))
    delegation: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    protocol_tasks: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    follow_ups: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    support_requests: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    approvals: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class IrCorrespondence(Base):
    __tablename__ = "ir_correspondence"

    id: Mapped[uuid.UUID] = uuid_pk()
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ir_engagement.id", ondelete="SET NULL"), index=True)
    sender: Mapped[str] = mapped_column(String(240), nullable=False)
    recipient: Mapped[str] = mapped_column(String(240), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="INTERNAL")
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="EN")
    owner: Mapped[str] = mapped_column(String(160), nullable=False)
    received_at: Mapped[dt.date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_deadline: Mapped[dt.date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ir_letter_template.id", ondelete="SET NULL"))
    template_version: Mapped[int | None] = mapped_column(Integer)
    translation_ref: Mapped[str | None] = mapped_column(String(120))
    document_ref: Mapped[str | None] = mapped_column(String(120))
    dispatch_ref: Mapped[str | None] = mapped_column(String(120))
    approved_version: Mapped[int | None] = mapped_column(Integer)
    approved_by_id: Mapped[str | None] = mapped_column(String(64))
    history: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class IrLetterTemplate(Base):
    __tablename__ = "ir_letter_template"
    __table_args__ = (UniqueConstraint("name", "language", "version", name="uq_ir_letter_template_name_lang_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class IrGift(Base):
    __tablename__ = "ir_gift"

    id: Mapped[uuid.UUID] = uuid_pk()
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ir_engagement.id", ondelete="SET NULL"), index=True)
    giver: Mapped[str] = mapped_column(String(240), nullable=False)
    recipient: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    gift_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    value_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    s011_status: Mapped[str] = mapped_column(String(16), nullable=False)
    s011_ref: Mapped[str | None] = mapped_column(String(120))
    flag_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()
