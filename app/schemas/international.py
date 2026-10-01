"""S083 schemas (mirror `packages/types/src/international.ts`)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import CamelModel, UtcDateTime, UUIDStr

Direction = Literal["INBOUND", "OUTBOUND"]
Classification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
Language = Literal["EN", "FR", "AR"]
EngagementType = Literal["VIP_VISIT", "COURTESY_CALL", "DELEGATION", "CONFERENCE", "BILATERAL_MEETING"]
EngagementStatus = Literal[
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CLOSED", "RETURNED", "CANCELLED"
]
TaskStatus = Literal["OPEN", "DONE", "EXCEPTION"]
SupportSystem = Literal["S084", "S078", "S086", "S074"]
HandoffStatus = Literal["REQUESTED", "ACKNOWLEDGED", "COMPLETED", "FAILED"]
CorrespondenceStatus = Literal[
    "RECEIVED", "DRAFT", "IN_REVIEW", "RETURNED", "APPROVED", "DISPATCHED", "AWAITING_RESPONSE", "RESPONDED", "CLOSED"
]


class EngagementIn(CamelModel):
    type: EngagementType
    direction: Direction
    title: str = Field(..., min_length=1, max_length=240)
    purpose: str = Field("", max_length=8000)
    partner_stakeholder_id: str | None = None
    partner_name: str = Field("", max_length=240)
    owner: str = Field("", max_length=160)
    host: str = Field("", max_length=160)
    venue: str = Field("", max_length=200)
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None
    time_zone: str = Field("Africa/Accra", max_length=64)
    classification: Classification = "INTERNAL"
    agenda_ref: str | None = Field(None, max_length=120)
    briefing_pack_ref: str | None = Field(None, max_length=120)
    minutes_ref: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _dates(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("endAt must be after startAt")
        return self


class TransitionIn(CamelModel):
    status: EngagementStatus
    comment: str = Field("", max_length=4000)


class DelegateIn(CamelModel):
    name: str = Field(..., min_length=1, max_length=200)
    contact_ref: str | None = Field(None, max_length=80)
    role: str = Field("", max_length=160)
    organisation: str = Field("", max_length=200)
    nationality: str = Field("", max_length=80)
    travel_request_ref: str | None = Field(None, max_length=80)


class TaskIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=240)
    mandatory: bool = True
    assignee: str = Field(..., min_length=1, max_length=160)
    due_date: dt.date | None = None
    evidence_ref: str | None = Field(None, max_length=120)


class FollowUpIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=240)
    owner: str = Field(..., min_length=1, max_length=160)
    due_date: dt.date
    mandatory: bool = True


class TaskUpdateIn(CamelModel):
    status: TaskStatus
    evidence_ref: str | None = Field(None, max_length=120)
    exception_reason: str | None = Field(None, max_length=2000)


class SupportIn(CamelModel):
    system: SupportSystem
    description: str = Field(..., min_length=1, max_length=2000)


class SupportStatusIn(CamelModel):
    status: HandoffStatus
    external_ref: str | None = Field(None, max_length=120)


class DelegateOut(DelegateIn):
    id: str


class TaskOut(CamelModel):
    id: str
    title: str
    mandatory: bool
    assignee: str
    due_date: dt.date | None
    status: str
    evidence_ref: str | None
    exception_reason: str | None


class FollowUpOut(CamelModel):
    id: str
    title: str
    owner: str
    due_date: dt.date
    mandatory: bool
    status: str
    exception_reason: str | None


class SupportOut(CamelModel):
    id: str
    system: str
    description: str
    external_ref: str | None
    status: str
    requested_at: str
    updated_at: str


class ApprovalOut(CamelModel):
    id: str
    decision: str
    comment: str
    actor: str
    version: int
    occurred_at: str


class EngagementOut(CamelModel):
    id: UUIDStr
    reference: str
    type: str
    direction: str
    title: str
    purpose: str
    partner_stakeholder_id: UUIDStr | None
    partner_name: str
    owner: str
    host: str
    venue: str
    start_at: UtcDateTime | None
    end_at: UtcDateTime | None
    time_zone: str
    classification: str
    status: str
    checklist_version: int
    agenda_ref: str | None
    briefing_pack_ref: str | None
    minutes_ref: str | None
    final_report_ref: str | None
    delegation: list[DelegateOut]
    protocol_tasks: list[TaskOut]
    follow_ups: list[FollowUpOut]
    support_requests: list[SupportOut]
    approvals: list[ApprovalOut]
    version: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class CorrespondenceIn(CamelModel):
    direction: Direction
    engagement_id: str | None = None
    sender: str = Field(..., min_length=1, max_length=240)
    recipient: str = Field(..., min_length=1, max_length=240)
    subject: str = Field(..., min_length=1, max_length=300)
    classification: Classification = "INTERNAL"
    language: Language = "EN"
    owner: str = Field(..., min_length=1, max_length=160)
    received_at: dt.date | None = None
    response_deadline: dt.date | None = None
    body: str = Field("", max_length=50000)
    template_id: str | None = None
    translation_ref: str | None = Field(None, max_length=120)
    document_ref: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _inbound(self):
        if self.direction == "INBOUND" and self.received_at is None:
            raise ValueError("receivedAt is required for inbound correspondence")
        return self


class CorrespondenceTransitionIn(CamelModel):
    status: CorrespondenceStatus
    comment: str = Field("", max_length=4000)


class CorrespondenceOut(CamelModel):
    id: UUIDStr
    reference: str
    direction: str
    engagement_id: UUIDStr | None
    sender: str
    recipient: str
    subject: str
    classification: str
    language: str
    owner: str
    received_at: dt.date | None
    sent_at: UtcDateTime | None
    response_deadline: dt.date | None
    status: str
    body: str
    template_id: UUIDStr | None
    template_version: int | None
    translation_ref: str | None
    document_ref: str | None
    dispatch_ref: str | None
    approved_version: int | None
    version: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class TemplateIn(CamelModel):
    name: str = Field(..., min_length=1, max_length=160)
    language: Language
    subject: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=50000)


class TemplateOut(CamelModel):
    id: UUIDStr
    name: str
    language: str
    version: int
    subject: str
    body: str
    active: bool
    updated_at: UtcDateTime


class GiftIn(CamelModel):
    direction: Literal["GIVEN", "RECEIVED"]
    engagement_id: str | None = None
    giver: str = Field(..., min_length=1, max_length=240)
    recipient: str = Field(..., min_length=1, max_length=240)
    description: str = Field(..., min_length=1, max_length=4000)
    gift_date: dt.date
    value_known: bool
    value: float | None = None
    currency: str | None = Field(None, max_length=3)

    @model_validator(mode="after")
    def _value(self):
        if not self.value_known and self.value is not None:
            raise ValueError("value must be empty when the value is unknown")
        if self.value_known:
            if self.value is None or self.value < 0:
                raise ValueError("Enter a value of zero or more")
            if not self.currency or len(self.currency) != 3 or not self.currency.isalpha():
                raise ValueError("currency must be a 3-letter code such as GHS")
            self.currency = self.currency.upper()
        return self


class GiftOut(CamelModel):
    id: UUIDStr
    direction: str
    engagement_id: UUIDStr | None
    giver: str
    recipient: str
    description: str
    gift_date: dt.date
    value_known: bool
    value: float | None
    currency: str | None
    s011_status: str
    s011_ref: str | None
    flag_attempts: int
    created_at: UtcDateTime
