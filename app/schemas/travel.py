"""
S084 Visa & Travel Authorisation schemas.

These mirror the TypeScript contracts in
`partner-crm/apps/travel-authorisation/src/features/requests/types.ts`, which are
re-exported from `packages/types/src/travel.ts`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel, UtcDateTime, UUIDStr

TravelDirection = Literal["Inbound", "Outbound"]

RequestStatus = Literal[
    "Draft",
    "Submitted",
    "Screening",
    "Pending approvals",
    "Approved",
    "Support issued",
    "Travel authorised",
    "Completed",
    "Closed",
    "Returned",
    "Rejected",
    "Cancelled",
]

ApprovalStatus = Literal["Pending", "Approved", "Returned", "Rejected", "Superseded", "Not required"]
IntegrationStatus = Literal["Complete", "Pending", "Failed", "Not started"]
EvidenceStatus = Literal["Received", "Missing", "Exception"]


class EvidenceItem(CamelModel):
    id: str | None = None
    label: str
    required: bool | None = True
    sensitive: bool | None = False
    status: EvidenceStatus
    reference: str | None = None
    exception_reason: str | None = None
    reviewed_by: str | None = None


class ApprovalStep(CamelModel):
    id: str
    label: str
    assignee: str
    status: ApprovalStatus
    decided_at: str | None = None
    comment: str | None = None
    record_version: int | None = None


class IntegrationHandoff(CamelModel):
    system: str
    label: str
    status: IntegrationStatus
    reference: str | None = None
    correlation_id: str | None = None
    note: str | None = None
    updated_at: str | None = None


class IssuedDocument(CamelModel):
    id: str
    type: Literal["Support letter", "Travel authorisation"]
    reference: str
    template_version: str
    signatory: str
    issued_at: str
    status: Literal["Current", "Superseded"]


class NotificationRecord(CamelModel):
    id: str
    subject: str
    recipient: str
    status: Literal["Delivered", "Pending", "Failed"]
    correlation_id: str
    sent_at: str


class ClosureRecord(CamelModel):
    outcome: str
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    claim_reference: str | None = None
    unresolved_actions: str | None = None
    closed_at: str | None = None


class Estimate(CamelModel):
    currency: str
    per_diem: float
    transport: float
    accommodation: float
    other: float | None = 0
    eligible_days: int | None = None
    daily_rate: float | None = None
    rate_version: str | None = None


class HistoryEntry(CamelModel):
    title: str
    detail: str
    at: str


class TravelRequestOut(CamelModel):
    id: UUIDStr
    reference: str
    direction: TravelDirection
    category: str
    traveller: str
    nationality: str | None = None
    purpose: str
    destination: str
    host: str | None = None
    start_date: dt.date
    end_date: dt.date
    owner: str
    requester: str | None = None
    student_number: str | None = None
    programme: str | None = None
    level: str | None = None
    sponsor: str | None = None
    emergency_contact: str | None = None
    return_declaration: bool | None = None
    status: RequestStatus
    next_action: str
    submitted_at: str | None = None
    updated_at: UtcDateTime
    source_reference: str | None = None
    policy_version: str
    record_version: int
    estimate: Estimate | None = None
    evidence: list[EvidenceItem]
    approvals: list[ApprovalStep]
    integrations: list[IntegrationHandoff]
    issued_documents: list[IssuedDocument] = Field(default_factory=list)
    notifications: list[NotificationRecord] = Field(default_factory=list)
    closure: ClosureRecord | None = None
    cancellation_reason: str | None = None
    last_change_reason: str | None = None
    history: list[HistoryEntry]


class TravelRequestIn(CamelModel):
    direction: TravelDirection
    category: str = Field(min_length=1, max_length=80)
    traveller: str = Field(min_length=1, max_length=200)
    nationality: str | None = None
    purpose: str = Field(min_length=1)
    destination: str = Field(min_length=1, max_length=200)
    host: str | None = None
    start_date: dt.date
    end_date: dt.date
    source_reference: str | None = None
    student_number: str | None = None
    programme: str | None = None
    level: str | None = None
    sponsor: str | None = None
    emergency_contact: str | None = None
    return_declaration: bool | None = None
    #: Client-generated UUID, so an optimistic UI keeps the id it navigated to.
    id: uuid.UUID | None = None

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, value: dt.date, info):
        start = info.data.get("start_date")
        if start and value < start:
            raise ValueError("End date cannot be earlier than start date.")
        return value


class EvidenceIn(CamelModel):
    """A decision on one checklist line. `detail` is the reference or the exception reason."""

    status: EvidenceStatus
    detail: str | None = None


class ApprovalDecisionIn(CamelModel):
    decision: Literal["Approved", "Returned", "Rejected"]
    comment: str = Field(min_length=1)


class EstimateIn(CamelModel):
    currency: str = Field(min_length=1, max_length=8)
    eligible_days: int = Field(ge=0)
    daily_rate: float = Field(ge=0)
    transport: float = Field(ge=0)
    accommodation: float = Field(ge=0)
    other: float = Field(default=0, ge=0)
    rate_version: str


class IssueDocumentIn(CamelModel):
    signatory: str = Field(min_length=1, max_length=200)
    template_version: str = Field(min_length=1, max_length=80)


class AmendmentIn(CamelModel):
    destination: str = Field(min_length=1, max_length=200)
    start_date: dt.date
    end_date: dt.date
    reason: str = Field(min_length=1)

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, value: dt.date, info):
        start = info.data.get("start_date")
        if start and value < start:
            raise ValueError("End date cannot be earlier than start date.")
        return value


class CancelIn(CamelModel):
    reason: str = Field(min_length=1)


class IntegrationIn(CamelModel):
    system: str = Field(min_length=1, max_length=40)
    status: IntegrationStatus
    reference: str | None = None
    note: str | None = None


class ClosureIn(CamelModel):
    outcome: str = Field(min_length=1)
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    claim_reference: str | None = None
    unresolved_actions: str | None = None


class TravelPolicyOut(CamelModel):
    id: UUIDStr
    policy_version: str
    rate_version: str
    currency: str
    daily_rates: dict[str, float]
    support_template: str
    authorisation_template: str
    escalation_days: int
    updated_by: str | None = None
    updated_at: UtcDateTime


class TravelPolicyIn(CamelModel):
    policy_version: str = Field(min_length=1, max_length=32)
    rate_version: str = Field(min_length=1, max_length=32)
    currency: str = Field(min_length=1, max_length=8)
    daily_rates: dict[str, float]
    support_template: str = Field(min_length=1, max_length=80)
    authorisation_template: str = Field(min_length=1, max_length=80)
    escalation_days: int = Field(ge=0, le=60)
