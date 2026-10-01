"""S088 schemas (mirror `packages/types/src/consultations.ts`)."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from app.models.consultations import ConsultationStatus
from app.schemas.common import CamelModel, UtcDateTime, UUIDStr

QuestionType = Literal[
    "SECTION", "SHORT_TEXT", "LONG_TEXT", "SINGLE_CHOICE", "MULTI_CHOICE", "DROPDOWN", "RATING", "NPS", "NUMBER", "DATE"
]
Operator = Literal["EQUALS", "NOT_EQUALS", "INCLUDES", "GREATER_THAN", "LESS_THAN", "ANSWERED"]
AudienceSource = Literal["PUBLIC", "CRM", "STUDENT", "ALUMNI", "EMPLOYER", "MIXED"]
CHOICE_TYPES = {"SINGLE_CHOICE", "MULTI_CHOICE", "DROPDOWN"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Condition(CamelModel):
    question_id: str = Field(..., min_length=1, max_length=80)
    operator: Operator
    value: str | float | int | None = None


class Translation(CamelModel):
    prompt: str = Field(..., max_length=2000)
    description: str | None = Field(None, max_length=4000)
    options: list[str] | None = None


class Question(CamelModel):
    id: str = Field(..., min_length=1, max_length=80)
    type: QuestionType
    prompt: str = Field(..., min_length=1, max_length=2000)
    description: str | None = Field(None, max_length=4000)
    required: bool = False
    options: list[str] | None = None
    min: float | None = None
    max: float | None = None
    min_label: str | None = Field(None, max_length=80)
    max_label: str | None = Field(None, max_length=80)
    visible_if: list[Condition] | None = None
    translations: dict[str, Translation] | None = None

    @model_validator(mode="after")
    def _shape(self):
        if self.type in CHOICE_TYPES and len([o for o in (self.options or []) if o.strip()]) < 2:
            raise ValueError(f"Question '{self.prompt[:40]}' needs at least two options")
        if self.type == "RATING" and self.min is not None and self.max is not None and self.max <= self.min:
            raise ValueError("Rating max must be greater than min")
        return self


class Trigger(CamelModel):
    id: str = Field(..., min_length=1, max_length=80)
    type: Literal["POST_EVENT", "REGISTRATION_COMPLETED", "CALENDAR"]
    source_ref: str = Field(..., min_length=1, max_length=120)
    delay_days: int = Field(0, ge=0, le=365)
    active: bool = True


class Theme(CamelModel):
    id: str
    label: str
    description: str = ""


class ConsultationIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=240)
    slug: str = Field(..., min_length=3, max_length=80)
    summary: str = Field("", max_length=1000)
    description: str = Field("", max_length=20000)
    category: str = Field("", max_length=80)
    languages: list[str] = Field(..., min_length=1, max_length=10)
    opens_at: UtcDateTime
    closes_at: UtcDateTime
    estimated_minutes: int = Field(5, ge=1, le=240)
    anonymous_allowed: bool = True
    collect_identity: bool = False
    audience_source: AudienceSource = "PUBLIC"
    audience_segment_ids: list[str] = Field(default_factory=list, max_length=50)
    questions: list[Question] = Field(..., min_length=1, max_length=200)
    triggers: list[Trigger] = Field(default_factory=list, max_length=20)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("slug may contain lowercase letters, digits and single hyphens")
        return v

    @model_validator(mode="after")
    def _consistency(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("closesAt must be after opensAt")
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Question IDs must be unique")
        if not any(q.type != "SECTION" for q in self.questions):
            raise ValueError("Add at least one question")
        known: set[str] = set()
        for question in self.questions:
            for condition in question.visible_if or []:
                if condition.question_id not in known:
                    raise ValueError(f"Skip logic on '{question.prompt[:40]}' must refer to an earlier question")
            known.add(question.id)
        if self.audience_source != "PUBLIC" and self.audience_source in ("CRM", "MIXED") and not self.audience_segment_ids:
            raise ValueError("Choose at least one S081 segment for a CRM audience")
        return self


class ConsultationCreate(ConsultationIn):
    id: uuid.UUID | None = None


class ConsultationOut(CamelModel):
    id: UUIDStr
    slug: str
    title: str
    summary: str
    description: str
    category: str
    status: str
    languages: list[str]
    opens_at: UtcDateTime
    closes_at: UtcDateTime
    estimated_minutes: int
    anonymous_allowed: bool
    collect_identity: bool
    audience_source: str
    audience_segment_ids: list[str]
    invited_count: int | None
    response_count: int
    questions: list[Question]
    triggers: list[Trigger]
    themes: list[Theme]
    outcome_summary: str | None
    approved_by: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class StatusIn(CamelModel):
    status: str
    comment: str | None = Field(None, max_length=2000)
    closes_at: UtcDateTime | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ConsultationStatus.ALL:
            raise ValueError(f"status must be one of: {', '.join(ConsultationStatus.ALL)}")
        return v


class OutcomeIn(CamelModel):
    outcome_summary: str = Field(..., min_length=20, max_length=20000)


class Respondent(CamelModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    stakeholder_group: str = Field("", max_length=120)


class SubmitIn(CamelModel):
    language: str = Field(..., min_length=1, max_length=32)
    answers: dict[str, str | list[str] | float | int] = Field(default_factory=dict)
    consent_to_identity_link: bool = False
    respondent: Respondent | None = None


class ResponseOut(CamelModel):
    id: UUIDStr
    consultation_id: UUIDStr
    submitted_at: UtcDateTime
    language: str
    answers: dict[str, str | list[str] | float | int]
    consent_to_identity_link: bool
    respondent: Respondent | None
    themes: dict[str, list[str]]


class SubmittedOut(CamelModel):
    id: UUIDStr


class InvitationIn(CamelModel):
    kind: Literal["INVITATION", "REMINDER"]
    segment_ids: list[str] = Field(..., min_length=1, max_length=50)


class InvitationOut(CamelModel):
    id: UUIDStr
    consultation_id: UUIDStr
    kind: str
    segment_ids: list[str]
    recipient_count: int
    excluded_count: int
    communication_ref: str | None
    sent_by: str
    sent_at: UtcDateTime


class ThemeIn(CamelModel):
    label: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=500)


class TagIn(CamelModel):
    question_id: str = Field(..., min_length=1, max_length=80)
    theme_ids: list[str] = Field(default_factory=list, max_length=20)
