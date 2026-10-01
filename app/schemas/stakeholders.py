"""S081 request/response schemas (mirror `packages/types/src/stakeholders.ts`)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import EmailStr, Field, field_validator

from app.models.stakeholders import (
    ConsentStatus,
    EngagementType,
    HealthLevel,
    PipelineStage,
    RelationshipStatus,
    ScreeningStatus,
    StakeholderCategory,
)
from app.schemas.common import CamelModel, UtcDateTime, UUIDStr


def _one_of(value: str | None, allowed: list[str], label: str) -> str | None:
    if value is not None and value not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return value


class StakeholderIn(CamelModel):
    name: str = Field(..., min_length=1, max_length=240)
    short_name: str = Field("", max_length=32)
    category: str
    owner: str = Field("", max_length=160)
    location: str = Field("", max_length=160)
    website: str = Field("", max_length=240)
    description: str = Field("", max_length=5000)
    health: str | None = None
    pipeline_stage: str | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return _one_of(v, StakeholderCategory.ALL, "category") or v

    @field_validator("health")
    @classmethod
    def _health(cls, v: str | None) -> str | None:
        return _one_of(v, HealthLevel.ALL, "health")

    @field_validator("pipeline_stage")
    @classmethod
    def _stage(cls, v: str | None) -> str | None:
        return _one_of(v, PipelineStage.ALL, "pipelineStage")


class StakeholderCreate(StakeholderIn):
    id: uuid.UUID | None = None
    force: bool = False
    override_reason: str | None = Field(None, max_length=1000)


class StatusIn(CamelModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _one_of(v, RelationshipStatus.ALL, "status") or v


class ImportIn(CamelModel):
    rows: list[StakeholderIn] = Field(..., max_length=5000)


class SkippedRow(CamelModel):
    row: int
    name: str
    reason: str


class ImportResult(CamelModel):
    created: int
    duplicates: int
    skipped: list[SkippedRow]


class ContactIn(CamelModel):
    name: str = Field(..., min_length=1, max_length=200)
    role: str = Field("", max_length=160)
    email: EmailStr
    phone: str = Field("", max_length=64)
    consent: str = "Not recorded"
    regulated: bool = False
    consent_date: dt.date | None = None
    consent_channel: str | None = None
    # Only honoured on update: `true` reactivates a deactivated contact.
    active: bool | None = None

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: str) -> str:
        return _one_of(v, ConsentStatus.ALL, "consent") or v

    @field_validator("consent_channel")
    @classmethod
    def _channel(cls, v: str | None) -> str | None:
        return _one_of(v, ConsentStatus.CHANNELS, "consentChannel")


class ContactCreate(ContactIn):
    id: uuid.UUID | None = None


class ScreeningDecisionIn(CamelModel):
    outcome: str
    notes: str = Field("", max_length=4000)
    case_ref: str | None = Field(None, max_length=120)

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, v: str) -> str:
        return _one_of(v, ScreeningStatus.DECISIONS, "outcome") or v


class S203DecisionIn(ScreeningDecisionIn):
    """Idempotent decision callback sent by S203."""

    event_id: str = Field(..., min_length=1, max_length=160)


class ConsentIn(CamelModel):
    consent: str
    consent_date: dt.date | None = None
    consent_channel: str | None = None

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: str) -> str:
        return _one_of(v, ConsentStatus.ALL, "consent") or v

    @field_validator("consent_channel")
    @classmethod
    def _channel(cls, v: str | None) -> str | None:
        return _one_of(v, ConsentStatus.CHANNELS, "consentChannel")


class EngagementIn(CamelModel):
    id: uuid.UUID | None = None
    type: str
    title: str = Field(..., min_length=1, max_length=240)
    summary: str = Field("", max_length=5000)
    date: dt.date | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _one_of(v, EngagementType.ALL, "type") or v


class ScreeningRecordOut(CamelModel):
    outcome: str
    reviewer: str
    reviewed_at: str
    notes: str
    case_ref: str | None = None


class ContactOut(CamelModel):
    id: UUIDStr
    name: str
    role: str
    email: str
    phone: str
    consent: str
    consent_date: dt.date | None = None
    consent_channel: str | None = None
    screening: str
    screening_record: ScreeningRecordOut | None = None
    active: bool


class S203SubjectOut(CamelModel):
    id: UUIDStr
    name: str
    role: str
    email: str
    phone: str


class S203StakeholderOut(CamelModel):
    id: UUIDStr
    name: str
    category: str


class S203ScreeningCaseOut(CamelModel):
    case_id: UUIDStr
    status: str
    submitted_at: UtcDateTime
    updated_at: UtcDateTime
    stakeholder: S203StakeholderOut
    subject: S203SubjectOut
    decision: ScreeningRecordOut | None = None
    decision_callback: str


class S203ActivityOut(CamelModel):
    id: UUIDStr
    occurred_at: UtcDateTime
    action: str
    actor: str
    summary: str
    before: dict | None = None
    after: dict | None = None


class EngagementOut(CamelModel):
    id: UUIDStr
    type: str
    title: str
    summary: str
    date: dt.date
    source: str


class StakeholderOut(CamelModel):
    id: UUIDStr
    name: str
    short_name: str
    category: str
    owner: str
    status: str
    health: str
    pipeline_stage: str
    last_engagement: str
    location: str
    website: str
    description: str
    contacts: list[ContactOut]
    engagements: list[EngagementOut]


class SegmentCriteria(CamelModel):
    categories: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    consented_only: bool = False

    @field_validator("categories")
    @classmethod
    def _categories(cls, v: list[str]) -> list[str]:
        for item in v:
            _one_of(item, StakeholderCategory.ALL, "categories")
        return v

    @field_validator("statuses")
    @classmethod
    def _statuses(cls, v: list[str]) -> list[str]:
        for item in v:
            _one_of(item, RelationshipStatus.ALL, "statuses")
        return v


class SegmentIn(CamelModel):
    name: str = Field(..., min_length=1, max_length=160)
    description: str = Field("", max_length=2000)
    categories: list[str] = Field(default_factory=list)
    used_by: list[str] = Field(default_factory=list)
    criteria: SegmentCriteria | None = None


class SegmentCreate(SegmentIn):
    id: uuid.UUID | None = None


class SegmentOut(CamelModel):
    id: UUIDStr
    name: str
    description: str
    members: int
    consented: int
    used_by: list[str]
    updated: str
    categories: list[str]
    criteria: SegmentCriteria


class SegmentMemberOut(CamelModel):
    stakeholder_id: UUIDStr
    stakeholder_name: str
    contact_id: UUIDStr
    contact_name: str
    email: str
    consent: str
