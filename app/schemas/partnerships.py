"""S082 schemas (mirror `packages/types/src/partnerships.ts`)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.partnerships import (
    AgreementType,
    ObligationStatus,
    PartnershipStatus,
    RenewalRecommendation,
    ReviewOutcome,
)
from app.schemas.common import CamelModel, UtcDateTime, UUIDStr


def _one_of(value: str, allowed: list[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return value


def _clean_list(values: list[str]) -> list[str]:
    return [v.strip() for v in values if v and v.strip()]


class PartnershipBase(CamelModel):
    stakeholder_id: uuid.UUID
    party_stakeholder_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    title: str = Field(..., min_length=1, max_length=240)
    agreement_type: str
    owner: str = Field(..., min_length=1, max_length=160)
    effective_date: dt.date | None = None
    expiry_date: dt.date | None = None
    value_commitment: str = Field("", max_length=4000)
    deliverables: list[str] = Field(default_factory=list, max_length=100)
    legal_contract_ref: str | None = Field(None, max_length=120)

    @field_validator("agreement_type")
    @classmethod
    def _type(cls, v: str) -> str:
        return _one_of(v, AgreementType.ALL, "agreementType")

    @field_validator("deliverables")
    @classmethod
    def _deliverables(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_date and self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiryDate must be after effectiveDate")
        return self


class PartnershipCreate(PartnershipBase):
    id: uuid.UUID | None = None


class PartnershipUpdate(PartnershipBase):
    signed_document_ref: str | None = Field(None, max_length=120)


class PartnershipImportRow(PartnershipBase):
    reference: str = Field(..., min_length=1, max_length=64)
    status: str
    signed_document_ref: str | None = Field(None, max_length=120)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _one_of(v, PartnershipStatus.ALL, "status")


class PartnershipImportIn(CamelModel):
    agreements: list[PartnershipImportRow] = Field(..., max_length=2000)


class PartnershipImportResult(CamelModel):
    imported: int
    skipped: int
    errors: list[str]


class TransitionIn(CamelModel):
    status: str
    note: str = Field("", max_length=2000)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _one_of(v, PartnershipStatus.ALL, "status")


class RenewIn(CamelModel):
    effective_date: dt.date
    expiry_date: dt.date
    legal_contract_ref: str = Field(..., min_length=1, max_length=120)
    signed_document_ref: str = Field(..., min_length=1, max_length=120)
    terms_summary: str = Field(..., min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _dates(self):
        if self.expiry_date <= self.effective_date:
            raise ValueError("expiryDate must be after effectiveDate")
        return self


class TerminateIn(CamelModel):
    terminated_at: dt.date
    reason: str = Field(..., min_length=1, max_length=4000)
    documentation_ref: str = Field(..., min_length=1, max_length=120)
    final_archive_ref: str = Field(..., min_length=1, max_length=120)


class TerminationOut(CamelModel):
    terminated_at: str
    reason: str
    documentation_ref: str
    final_archive_ref: str
    approved_by: str


class PartnershipOut(CamelModel):
    id: UUIDStr
    stakeholder_id: UUIDStr
    party_stakeholder_ids: list[str]
    reference: str
    title: str
    agreement_type: str
    status: str
    owner: str
    effective_date: dt.date | None
    expiry_date: dt.date | None
    value_commitment: str
    deliverables: list[str]
    legal_contract_ref: str | None
    signed_document_ref: str | None
    renewal_count: int
    termination: TerminationOut | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ObligationCreate(CamelModel):
    id: uuid.UUID | None = None
    agreement_id: uuid.UUID | None = None
    title: str = Field(..., min_length=1, max_length=240)
    description: str = Field("", max_length=4000)
    owner: str = Field(..., min_length=1, max_length=160)
    due_date: dt.date
    reminder_lead_days: int | None = Field(None, ge=0, le=365)
    escalation_owner: str | None = Field(None, max_length=160)


class ObligationUpdate(CamelModel):
    title: str = Field(..., min_length=1, max_length=240)
    description: str = Field("", max_length=4000)
    owner: str = Field(..., min_length=1, max_length=160)
    due_date: dt.date
    status: str
    evidence_references: list[str] = Field(default_factory=list, max_length=100)
    reminder_lead_days: int | None = Field(None, ge=0, le=365)
    escalation_owner: str | None = Field(None, max_length=160)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _one_of(v, ObligationStatus.ALL, "status")

    @field_validator("evidence_references")
    @classmethod
    def _evidence(cls, v: list[str]) -> list[str]:
        return _clean_list(v)


class ObligationOut(CamelModel):
    id: UUIDStr
    agreement_id: UUIDStr
    title: str
    description: str
    owner: str
    due_date: dt.date
    status: str
    evidence_references: list[str]
    reminder_lead_days: int | None
    escalation_owner: str | None
    updated_at: UtcDateTime


class ProgressIn(CamelModel):
    note: str = Field(..., min_length=1, max_length=4000)
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _one_of(v, ObligationStatus.ALL, "status")


class ProgressOut(CamelModel):
    id: UUIDStr
    obligation_id: UUIDStr
    note: str
    status: str
    actor: str
    created_at: UtcDateTime


class ReviewIn(CamelModel):
    review_date: dt.date
    reviewer: str = Field(..., min_length=1, max_length=200)
    outcome: str
    summary: str = Field(..., min_length=1, max_length=8000)
    period_start: dt.date
    period_end: dt.date
    outputs: list[str] = Field(..., min_length=1, max_length=100)
    strategic_score: Literal[1, 2, 3, 4, 5]
    issues: list[str] = Field(default_factory=list, max_length=100)
    recommendations: list[str] = Field(..., min_length=1, max_length=100)
    renewal_recommendation: str
    next_review_date: dt.date

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, v: str) -> str:
        return _one_of(v, ReviewOutcome.ALL, "outcome")

    @field_validator("renewal_recommendation")
    @classmethod
    def _rec(cls, v: str) -> str:
        return _one_of(v, RenewalRecommendation.ALL, "renewalRecommendation")

    @field_validator("outputs", "issues", "recommendations")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @model_validator(mode="after")
    def _dates(self):
        if self.period_end < self.period_start:
            raise ValueError("periodEnd must follow periodStart")
        if self.next_review_date <= self.review_date:
            raise ValueError("nextReviewDate must be after reviewDate")
        if not self.outputs:
            raise ValueError("At least one realised output is required")
        if not self.recommendations:
            raise ValueError("At least one recommendation is required")
        return self


class ReviewCreate(ReviewIn):
    id: uuid.UUID | None = None
    agreement_id: uuid.UUID | None = None


class ReviewOut(CamelModel):
    id: UUIDStr
    agreement_id: UUIDStr
    review_date: dt.date
    reviewer: str
    outcome: str
    summary: str
    period_start: dt.date
    period_end: dt.date
    outputs: list[str]
    strategic_score: int
    issues: list[str]
    recommendations: list[str]
    renewal_recommendation: str
    next_review_date: dt.date


class RenewalOut(CamelModel):
    id: UUIDStr
    agreement_id: UUIDStr
    previous_effective_date: dt.date | None
    previous_expiry_date: dt.date | None
    previous_legal_contract_ref: str | None
    previous_signed_document_ref: str | None
    effective_date: dt.date
    expiry_date: dt.date
    legal_contract_ref: str
    signed_document_ref: str
    terms_summary: str
    renewed_by: str
    renewed_at: UtcDateTime


class AlertsConfigIn(CamelModel):
    agreement_id: uuid.UUID | None = None
    recipients: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: list[str]) -> list[str]:
        cleaned = _clean_list(v)
        for item in cleaned:
            if "@" not in item:
                raise ValueError(f"{item} is not an email address")
        if not cleaned:
            raise ValueError("At least one recipient is required")
        return cleaned


class RenewalAlertOut(CamelModel):
    id: UUIDStr
    agreement_id: UUIDStr
    milestone_days: int
    scheduled_for: dt.date
    recipients: list[str]
    status: str
    communication_ref: str | None
    sent_at: UtcDateTime | None
    acknowledged_at: UtcDateTime | None
    acknowledged_by: str | None


class HistoryOut(CamelModel):
    id: UUIDStr
    agreement_id: UUIDStr
    action: str
    summary: str
    actor: str
    occurred_at: UtcDateTime


class IntegrationHealthOut(CamelModel):
    system: str
    name: str
    state: str
    last_checked_at: UtcDateTime | None
    detail: str
