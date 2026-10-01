"""
Append-only audit log (S204 feed) and the transactional integration outbox.

Audit rows are hash-chained: each row stores the SHA-256 of its own content plus
the previous row's hash, so any edit or deletion breaks the chain and is
detectable. PostgreSQL triggers (migration 0001) additionally block UPDATE and
DELETE on the audit table.

Outbox rows are written in the same transaction as the business change and
relayed to S074 / S203 / S204 / S011 / S225 by Celery; a failed delivery never rolls
back the business record.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, uuid_pk


class AuditEvent(Base):
    __tablename__ = "pcrm_audit_event"
    __table_args__ = (Index("ix_pcrm_audit_event_resource", "resource_type", "resource_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    occurred_at: Mapped[datetime] = created_at_column()
    action: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class OutboxStatus:
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    ALL = [PENDING, SENT, FAILED]


class OutboxEvent(Base):
    __tablename__ = "pcrm_outbox_event"
    __table_args__ = (Index("ix_pcrm_outbox_event_status_target", "status", "target_system"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    target_system: Mapped[str] = mapped_column(String(16), nullable=False)  # S074, S203, S204, S011, S225
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    external_ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at_column()
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
