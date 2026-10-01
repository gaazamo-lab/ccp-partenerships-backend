"""
S084 Visa & Travel Authorisation.

One aggregate: the travel request. Its sub-items — evidence checklist, approval
chain, integration handoffs, issued documents, notifications and history — are
JSON arrays on the row, the same shape the S084 frontend already holds them in
and the same choice made for S083 engagement sub-items. They are only ever read
through the parent request. Move them to child tables if they ever need to be
reported on independently.

CLET does not own the downstream outcomes: visas are decided by missions, funds
are disbursed by S144, and documents are stored in S003. Those are recorded here
as references and handoff statuses only.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class TravelRequest(Base):
    __tablename__ = "travel_request"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Human reference shown throughout the workspace, e.g. `S084-2026-0043`.
    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)

    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    traveller: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    nationality: Mapped[str | None] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    host: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    requester: Mapped[str | None] = mapped_column(String(200))

    # Student outbound travel only; the authoritative records stay in S027/S031.
    student_number: Mapped[str | None] = mapped_column(String(60))
    programme: Mapped[str | None] = mapped_column(String(200))
    level: Mapped[str | None] = mapped_column(String(60))
    sponsor: Mapped[str | None] = mapped_column(String(200))
    emergency_contact: Mapped[str | None] = mapped_column(String(200))
    return_declaration: Mapped[bool | None] = mapped_column(Boolean)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Draft", index=True)
    next_action: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    submitted_at: Mapped[str | None] = mapped_column(String(32))
    source_reference: Mapped[str | None] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="TRV-4.2")
    #: Bumped on every state-changing write; approvals carry the version they decided on.
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    estimate: Mapped[dict | None] = mapped_column(JSONType)
    closure: Mapped[dict | None] = mapped_column(JSONType)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    last_change_reason: Mapped[str | None] = mapped_column(Text)

    evidence: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    approvals: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    integrations: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    issued_documents: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    notifications: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    history: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class TravelPolicy(Base):
    """
    The single configuration row the DTI administrator edits: per-diem rates,
    template versions and the escalation window. Versioned so an estimate can
    name the rate version it was calculated against.
    """

    __tablename__ = "travel_policy"

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="TRV-4.2")
    rate_version: Mapped[str] = mapped_column(String(32), nullable=False, default="RATE-2026.1")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="GHS")
    #: `{"<band>": <daily rate>}`, e.g. `{"Regional": 1200}`.
    daily_rates: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    support_template: Mapped[str] = mapped_column(String(80), nullable=False, default="S084 standard v3.1")
    authorisation_template: Mapped[str] = mapped_column(String(80), nullable=False, default="S084 standard v3.1")
    escalation_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    updated_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
