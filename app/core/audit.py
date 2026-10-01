"""
Audit and outbox writers.

`emit_audit` appends a hash-chained `AuditEvent` and queues its S204 forward in
the caller's transaction; the caller commits. `enqueue` queues any other
integration message (S074 notifications, S011 gift flags, S225 analytics).
Both are idempotent on `idempotency_key`, so retried requests never duplicate
downstream effects.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity
from app.models.audit import AuditEvent, OutboxEvent, OutboxStatus
from app.models.base import utcnow


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def to_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


async def enqueue(
    db: AsyncSession,
    *,
    target_system: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> OutboxEvent:
    existing = await db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    row = OutboxEvent(
        target_system=target_system,
        event_type=event_type,
        payload=to_jsonable(payload),
        idempotency_key=idempotency_key,
        status=OutboxStatus.PENDING,
        next_attempt_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def emit_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID = "",
    identity: Identity | None = None,
    summary: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    outcome: str = "success",
) -> AuditEvent:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        # Serialise chain appends across concurrent transactions; released on commit.
        await db.execute(text("SELECT pg_advisory_xact_lock(204204)"))
    previous = await db.scalar(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1))
    sequence = (previous.sequence + 1) if previous else 1
    prev_hash = previous.row_hash if previous else ""
    occurred_at = utcnow()
    content = {
        "sequence": sequence,
        "occurredAt": occurred_at.isoformat(),
        "action": action,
        "resourceType": resource_type,
        "resourceId": str(resource_id),
        "actorId": identity.sub if identity else "system",
        "outcome": outcome,
        "before": to_jsonable(before),
        "after": to_jsonable(after),
        "prevHash": prev_hash,
    }
    row_hash = hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()
    event = AuditEvent(
        sequence=sequence,
        occurred_at=occurred_at,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        actor_id=identity.sub if identity else "system",
        actor_email=identity.email if identity else "",
        actor_role=identity.role if identity else "",
        outcome=outcome,
        summary=summary,
        before=content["before"],
        after=content["after"],
        correlation_id=identity.correlation_id if identity else "",
        source_ip=identity.source_ip if identity else "",
        prev_hash=prev_hash,
        row_hash=row_hash,
    )
    db.add(event)
    await db.flush()
    await enqueue(
        db,
        target_system="S204",
        event_type=action,
        payload={**content, "rowHash": row_hash, "summary": summary},
        idempotency_key=f"s204:{event.id}",
    )
    return event


async def audit_chain_is_intact(db: AsyncSession) -> bool:
    """Recompute every row hash in order; False if any row was altered or removed."""
    rows = (await db.scalars(select(AuditEvent).order_by(AuditEvent.sequence))).all()
    prev_hash = ""
    for expected_sequence, row in enumerate(rows, start=1):
        if row.sequence != expected_sequence or row.prev_hash != prev_hash:
            return False
        occurred = row.occurred_at
        content = {
            "sequence": row.sequence,
            "occurredAt": (occurred if occurred.tzinfo else occurred.replace(tzinfo=UTC)).isoformat(),
            "action": row.action,
            "resourceType": row.resource_type,
            "resourceId": row.resource_id,
            "actorId": row.actor_id,
            "outcome": row.outcome,
            "before": row.before,
            "after": row.after,
            "prevHash": row.prev_hash,
        }
        if hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest() != row.row_hash:
            return False
        prev_hash = row.row_hash
    return True


async def audit_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(AuditEvent)) or 0)
