"""
S081 business rules: duplicate detection, the S203 screening gate, relationship
status derivation and live segment resolution.

Pure helpers take ORM objects and never touch the session, so they are unit
testable; query helpers take an `AsyncSession`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.models.stakeholders import (
    ConsentStatus,
    RelationshipStatus,
    ScreeningStatus,
    Segment,
    Stakeholder,
    StakeholderCategory,
    StakeholderContact,
)

# Domains that identify individual learner/alumni records, which S081 must not
# hold (SRS FR-A-02: NLEMS S027, HRMS S140 and Alumni CRM S034 own those people).
INDIVIDUAL_RECORD_DOMAINS = ("students.gsl.edu.gh", "alumni.gsl.edu.gh", "student.clet.gov.gh")


def normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def normalized_site(value: str | None) -> str:
    site = normalized(value)
    if not site:
        return ""
    host = urlsplit(site if "://" in site else f"//{site}").netloc or site
    return host.removeprefix("www.").rstrip("/")


def make_short_name(name: str) -> str:
    return "".join(part[0] for part in name.split()[:3] if part).upper()


def reject_individual_records(website: str) -> None:
    host = normalized_site(website)
    if any(host == domain or host.endswith(f".{domain}") for domain in INDIVIDUAL_RECORD_DOMAINS):
        raise ValidationFailed(
            "S081 holds organisations only. Students, staff and alumni are managed in NLEMS, HRMS and the Alumni CRM.",
            code="INDIVIDUAL_RECORD_REJECTED",
            field_errors={"website": ["Individual learner or alumni domains are not allowed."]},
        )


async def find_duplicate(db: AsyncSession, *, name: str, website: str, except_id: uuid.UUID | None = None) -> Stakeholder | None:
    rows = (await db.scalars(select(Stakeholder))).all()
    target_name, target_site = normalized(name), normalized_site(website)
    for row in rows:
        if except_id is not None and row.id == except_id:
            continue
        if normalized(row.name) == target_name or (target_site and normalized_site(row.website) == target_site):
            return row
    return None


def is_regulated(category: str) -> bool:
    return category in StakeholderCategory.REGULATED


def has_blocking_screening(stakeholder: Stakeholder) -> bool:
    return any(c.active and c.screening in ScreeningStatus.BLOCKING for c in stakeholder.contacts)


def derive_status(stakeholder: Stakeholder) -> str:
    """Screening pending while any active contact is unscreened; otherwise leave manual states alone."""
    if stakeholder.status == RelationshipStatus.INACTIVE:
        return stakeholder.status
    if has_blocking_screening(stakeholder):
        return RelationshipStatus.SCREENING_PENDING
    if stakeholder.status == RelationshipStatus.SCREENING_PENDING:
        return RelationshipStatus.ACTIVE
    return stakeholder.status


def last_engagement(stakeholder: Stakeholder) -> str:
    if not stakeholder.engagements:
        return "Not yet engaged"
    return max(e.date for e in stakeholder.engagements).isoformat()


def serialize_stakeholder(stakeholder: Stakeholder) -> dict:
    return {
        "id": stakeholder.id,
        "name": stakeholder.name,
        "short_name": stakeholder.short_name,
        "category": stakeholder.category,
        "owner": stakeholder.owner,
        "status": stakeholder.status,
        "health": stakeholder.health,
        "pipeline_stage": stakeholder.pipeline_stage,
        "last_engagement": last_engagement(stakeholder),
        "location": stakeholder.location,
        "website": stakeholder.website,
        "description": stakeholder.description,
        "contacts": list(stakeholder.contacts),
        "engagements": sorted(stakeholder.engagements, key=lambda e: (e.date, e.created_at), reverse=True),
    }


async def load_stakeholder(db: AsyncSession, stakeholder_id: uuid.UUID) -> Stakeholder:
    row = await db.scalar(select(Stakeholder).where(Stakeholder.id == stakeholder_id).execution_options(populate_existing=True))
    if row is None:
        raise NotFound("That stakeholder does not exist.", code="STAKEHOLDER_NOT_FOUND")
    return row


async def load_contact(db: AsyncSession, contact_id: uuid.UUID) -> StakeholderContact:
    row = await db.get(StakeholderContact, contact_id)
    if row is None:
        raise NotFound("That contact does not exist.", code="CONTACT_NOT_FOUND")
    return row


async def email_in_use(db: AsyncSession, email: str, *, except_id: uuid.UUID | None = None) -> bool:
    query = select(func.count()).select_from(StakeholderContact).where(func.lower(StakeholderContact.email) == normalized(email))
    if except_id is not None:
        query = query.where(StakeholderContact.id != except_id)
    return bool(await db.scalar(query))


# ── Segments ──


@dataclass(frozen=True)
class SegmentMember:
    stakeholder: Stakeholder
    contact: StakeholderContact


def segment_criteria(segment: Segment) -> dict:
    criteria = dict(segment.criteria or {})
    criteria.setdefault("categories", [])
    criteria.setdefault("statuses", [])
    criteria.setdefault("owners", [])
    criteria.setdefault("consentedOnly", False)
    return criteria


def resolve_members(stakeholders: Iterable[Stakeholder], criteria: dict) -> tuple[list[SegmentMember], int]:
    """
    Eligible contacts for a segment right now, and how many of them have consent.

    Excludes inactive stakeholders, inactive contacts and contacts whose S203
    screening is not complete; with `consentedOnly` only consented contacts count.
    """
    categories, statuses, owners = criteria["categories"], criteria["statuses"], criteria["owners"]
    members: list[SegmentMember] = []
    consented = 0
    for stakeholder in stakeholders:
        if stakeholder.status == RelationshipStatus.INACTIVE:
            continue
        if categories and stakeholder.category not in categories:
            continue
        if statuses and stakeholder.status not in statuses:
            continue
        if owners and stakeholder.owner not in owners:
            continue
        for contact in stakeholder.contacts:
            if not contact.active or contact.screening in ScreeningStatus.BLOCKING:
                continue
            has_consent = contact.consent == ConsentStatus.CONSENTED
            if criteria["consentedOnly"] and not has_consent:
                continue
            members.append(SegmentMember(stakeholder, contact))
            consented += int(has_consent)
    return members, consented


def serialize_segment(segment: Segment, stakeholders: list[Stakeholder]) -> dict:
    criteria = segment_criteria(segment)
    members, consented = resolve_members(stakeholders, criteria)
    return {
        "id": segment.id,
        "name": segment.name,
        "description": segment.description,
        "members": len(members),
        "consented": consented,
        "used_by": list(segment.used_by or []),
        "updated": segment.updated_at.isoformat(),
        "categories": criteria["categories"],
        "criteria": {
            "categories": criteria["categories"],
            "statuses": criteria["statuses"],
            "owners": criteria["owners"],
            "consented_only": criteria["consentedOnly"],
        },
    }
