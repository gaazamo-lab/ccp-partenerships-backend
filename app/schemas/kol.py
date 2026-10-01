"""S092 schemas (mirror `packages/types/src/kol.ts`)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common import CamelModel, UtcDateTime, UUIDStr

Category = Literal[
    "SENIOR_ADVOCATE",
    "JUDGE",
    "RETIRED_JUDGE",
    "ACADEMIC",
    "POLICY_INFLUENCER",
    "PRACTITIONER",
    "MEDIA_PERSONALITY",
    "ALUMNUS",
]
Status = Literal["PROSPECT", "ACTIVE", "DORMANT", "ARCHIVED"]
Influence = Literal["EMERGING", "ESTABLISHED", "NATIONAL", "INTERNATIONAL"]
Availability = Literal["AVAILABLE", "LIMITED", "UNAVAILABLE"]
Risk = Literal["NONE", "LOW", "MEDIUM", "HIGH"]
EngagementType = Literal["OP_ED", "PANEL", "KEYNOTE", "WEBINAR", "PODCAST", "CONSULTATION", "CAMPAIGN", "MEDIA_INTERVIEW"]
EngagementStage = Literal["PLANNED", "INVITED", "CONFIRMED", "COMPLETED", "DECLINED", "CANCELLED"]
ContentType = Literal["OP_ED", "ARTICLE", "BLOG_POST", "VIDEO", "PODCAST_EPISODE"]
ContentStage = Literal["COMMISSIONED", "DRAFT_SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "PUBLISHED", "WITHDRAWN"]


def _tags(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        clean = value.strip()
        if clean and clean.lower() not in seen:
            seen[clean.lower()] = clean
    return list(seen.values())


class KolIn(CamelModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    honorific: str = Field("", max_length=60)
    category: Category
    organisation: str = Field("", max_length=200)
    position: str = Field("", max_length=200)
    stakeholder_id: str | None = None
    alumni_ref: str | None = Field(None, max_length=80)
    email: EmailStr | Literal[""] = ""
    phone: str = Field("", max_length=64)
    expertise: list[str] = Field(default_factory=list, max_length=30)
    influence_areas: list[str] = Field(default_factory=list, max_length=30)
    influence_level: Influence
    availability: Availability
    relationship_owner: str = Field(..., min_length=1, max_length=160)
    status: Status = "PROSPECT"
    risk_level: Risk = "NONE"
    risk_notes: str = Field("", max_length=4000)
    bio: str = Field("", max_length=8000)

    @field_validator("expertise", "influence_areas")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return _tags(v)

    @model_validator(mode="after")
    def _risk(self):
        if self.risk_level in ("MEDIUM", "HIGH") and not self.risk_notes.strip():
            raise ValueError("riskNotes are required when the risk level is medium or high")
        return self


class KolOut(CamelModel):
    id: UUIDStr
    full_name: str
    honorific: str
    category: str
    organisation: str
    position: str
    stakeholder_id: UUIDStr | None
    alumni_ref: str | None
    email: str
    phone: str
    expertise: list[str]
    influence_areas: list[str]
    influence_level: str
    availability: str
    relationship_owner: str
    status: str
    risk_level: str
    risk_notes: str
    bio: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class EngagementIn(CamelModel):
    type: EngagementType
    title: str = Field(..., min_length=1, max_length=240)
    scheduled_for: dt.date | None = None
    owner: str = Field(..., min_length=1, max_length=160)
    external_ref: str | None = Field(None, max_length=120)
    notes: str = Field("", max_length=4000)


class EngagementStageIn(CamelModel):
    stage: EngagementStage
    note: str = Field("", max_length=2000)


class ParticipationIn(CamelModel):
    attended: bool
    outputs: str = Field("", max_length=4000)
    feedback: str = Field("", max_length=4000)
    contribution_score: Literal[1, 2, 3, 4, 5]


class ParticipationOut(ParticipationIn):
    recorded_at: str
    recorded_by: str


class EngagementOut(CamelModel):
    id: UUIDStr
    kol_id: UUIDStr
    type: str
    title: str
    stage: str
    scheduled_for: dt.date | None
    owner: str
    external_ref: str | None
    notes: str
    participation: ParticipationOut | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ContentIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=240)
    content_type: ContentType
    due_date: dt.date | None = None


class ContentStageIn(CamelModel):
    stage: ContentStage
    draft_ref: str | None = Field(None, max_length=120)
    review_notes: str | None = Field(None, max_length=4000)
    cms_ref: str | None = Field(None, max_length=120)
    published_url: str | None = Field(None, max_length=500)


class ContentOut(CamelModel):
    id: UUIDStr
    kol_id: UUIDStr
    title: str
    content_type: str
    stage: str
    due_date: dt.date | None
    draft_ref: str | None
    reviewer: str | None
    review_notes: str
    cms_ref: str | None
    published_url: str | None
    published_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class MentionIn(CamelModel):
    content_id: str | None = None
    outlet: str = Field(..., min_length=1, max_length=160)
    headline: str = Field(..., min_length=1, max_length=400)
    url: str = Field("", max_length=500)
    published_at: dt.date
    reach: int = Field(..., ge=0, le=1_000_000_000)
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]


class MentionOut(CamelModel):
    id: UUIDStr
    kol_id: UUIDStr
    content_id: UUIDStr | None
    outlet: str
    headline: str
    url: str
    published_at: dt.date
    reach: int
    sentiment: str
    source: str
