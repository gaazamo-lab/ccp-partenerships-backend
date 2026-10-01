"""
S083 rules (partner-crm `docs/architecture/new-module-rules.md`, S083 and the
SRS §4 state model). Pure helpers operate on the ORM rows; routers persist.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.international import IrCorrespondence, IrEngagement

ENGAGEMENT_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"UNDER_REVIEW", "CANCELLED"},
    "UNDER_REVIEW": {"APPROVED", "RETURNED", "CANCELLED"},
    "RETURNED": {"SUBMITTED", "CANCELLED"},
    "APPROVED": {"SCHEDULED", "CANCELLED"},
    "SCHEDULED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    "COMPLETED": {"CLOSED"},
    "CLOSED": {"IN_PROGRESS"},
    "CANCELLED": set(),
}
APPROVAL_DECISIONS = {"APPROVED", "RETURNED"}
COMMENT_REQUIRED = {"RETURNED", "CANCELLED"}
MATERIAL_FIELDS = ("title", "purpose", "start_at", "end_at", "time_zone", "venue", "host", "partner_name", "type", "direction")

INBOUND_TRANSITIONS: dict[str, set[str]] = {
    "RECEIVED": {"AWAITING_RESPONSE", "CLOSED"},
    "AWAITING_RESPONSE": {"RESPONDED", "CLOSED"},
    "RESPONDED": {"CLOSED"},
    "CLOSED": set(),
}
OUTBOUND_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"IN_REVIEW"},
    "IN_REVIEW": {"APPROVED", "RETURNED"},
    "RETURNED": {"IN_REVIEW"},
    "APPROVED": {"DISPATCHED", "IN_REVIEW"},
    "DISPATCHED": {"AWAITING_RESPONSE", "CLOSED"},
    "AWAITING_RESPONSE": {"RESPONDED", "CLOSED"},
    "RESPONDED": {"CLOSED"},
    "CLOSED": set(),
}


def item_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return utcnow().isoformat()


def engagement_blockers(engagement: IrEngagement, target: str) -> list[str]:
    blockers: list[str] = []
    if target == "SUBMITTED":
        for label, value in (("purpose", engagement.purpose), ("owner", engagement.owner), ("time zone", engagement.time_zone)):
            if not (value or "").strip():
                blockers.append(f"Add the {label}.")
        if engagement.start_at is None or engagement.end_at is None:
            blockers.append("Set the start and end times.")
    if target == "SCHEDULED":
        open_tasks = [t for t in engagement.protocol_tasks if t["mandatory"] and t["status"] == "OPEN"]
        if open_tasks:
            blockers.append(f"Complete or except {len(open_tasks)} mandatory protocol task(s) before scheduling.")
    if target == "CLOSED":
        open_follow_ups = [f for f in engagement.follow_ups if f["mandatory"] and f["status"] == "OPEN"]
        if open_follow_ups:
            blockers.append(f"Complete or except {len(open_follow_ups)} mandatory follow-up(s) before closing.")
        if not engagement.minutes_ref:
            blockers.append("Attach the minutes reference before closing.")
    return blockers


def approval_decision(current: str, target: str) -> str | None:
    if target in ("SUBMITTED",):
        return "SUBMITTED"
    if current == "UNDER_REVIEW" and target in APPROVAL_DECISIONS:
        return target
    if current == "CLOSED" and target == "IN_PROGRESS":
        return "REOPENED"
    if target == "CANCELLED":
        return "CANCELLED"
    return None


def _comparable(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=dt.UTC)).astimezone(dt.UTC)
    return value


def is_material_change(engagement: IrEngagement, incoming: dict[str, Any]) -> bool:
    return any(_comparable(getattr(engagement, f)) != _comparable(incoming.get(f)) for f in MATERIAL_FIELDS)


def find_item(items: list[dict], item_key: str) -> dict | None:
    return next((item for item in items if item["id"] == item_key), None)


def apply_task_update(
    item: dict, status: str, evidence_ref: str | None, exception_reason: str | None, *, needs_evidence: bool
) -> None:
    from app.core.errors import ValidationFailed

    if status == "DONE" and needs_evidence and item.get("mandatory") and not (evidence_ref or item.get("evidenceRef")):
        raise ValidationFailed("Attach evidence to complete a mandatory task.", field_errors={"evidenceRef": ["Required."]})
    if status == "EXCEPTION" and not (exception_reason or "").strip():
        raise ValidationFailed("Record why this item is excepted.", field_errors={"exceptionReason": ["Required."]})
    item["status"] = status
    if evidence_ref:
        item["evidenceRef"] = evidence_ref
    item["exceptionReason"] = exception_reason if status == "EXCEPTION" else None


async def next_reference(db: AsyncSession, model, prefix: str) -> str:
    year = dt.date.today().year
    stem = f"CLET/{prefix}/{year}/"
    count = await db.scalar(select(func.count()).select_from(model).where(model.reference.like(f"{stem}%")))
    sequence = int(count or 0) + 1
    while await db.scalar(select(model.id).where(model.reference == f"{stem}{sequence:03d}")):
        sequence += 1
    return f"{stem}{sequence:03d}"


def overlap(a: IrEngagement, b: IrEngagement) -> bool:
    if not (a.start_at and a.end_at and b.start_at and b.end_at):
        return False
    return _comparable(a.start_at) < _comparable(b.end_at) and _comparable(b.start_at) < _comparable(a.end_at)


def clashes(target: IrEngagement, others: list[IrEngagement]) -> list[IrEngagement]:
    result = []
    for other in others:
        if other.id == target.id or other.status == "CANCELLED" or not overlap(target, other):
            continue
        same_host = target.host and other.host and target.host.strip().lower() == other.host.strip().lower()
        same_venue = target.venue and other.venue and target.venue.strip().lower() == other.venue.strip().lower()
        if same_host or same_venue:
            result.append(other)
    return result


def correspondence_transitions(item: IrCorrespondence) -> set[str]:
    table = INBOUND_TRANSITIONS if item.direction == "INBOUND" else OUTBOUND_TRANSITIONS
    return table.get(item.status, set())


def render_template(body: str, values: dict[str, str]) -> str:
    rendered = body
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered
