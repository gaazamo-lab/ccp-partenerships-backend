"""S091 schemas (mirror `packages/types/src/microsites.ts`)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel, UtcDateTime, UUIDStr

Purpose = Literal["ANNUAL_REPORT", "DONOR_IMPACT", "CAMPAIGN", "EVENT_HUB", "THOUGHT_LEADERSHIP"]
Access = Literal["PUBLIC", "PASSWORD", "NAMED_AUDIENCE"]
BlockType = Literal[
    "HERO", "RICH_TEXT", "METRICS", "FUND_UTILISATION", "STORY", "QUOTE", "GALLERY", "CALL_TO_ACTION", "DOWNLOADS"
]
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58})[a-z0-9]$")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def valid_slug(value: str) -> str:
    if not SLUG.match(value) or "--" in value:
        raise ValueError("slug must be 3–60 lowercase letters, digits or single hyphens")
    return value


class Metric(CamelModel):
    label: str = Field(..., max_length=120)
    value: str = Field(..., max_length=60)
    source_ref: str = Field("", max_length=120)

    @field_validator("source_ref")
    @classmethod
    def _source(cls, v: str) -> str:
        # Figures must be traceable to Analytics (S225) or Grants Management (S150).
        if v and not (v.startswith("S225:") or v.startswith("S150:")):
            raise ValueError("sourceRef must start with S225: or S150:")
        return v


class Allocation(CamelModel):
    label: str = Field(..., max_length=120)
    amount: float = Field(..., ge=0)


class Link(CamelModel):
    label: str = Field(..., max_length=120)
    url: str = Field(..., max_length=500)

    @field_validator("url")
    @classmethod
    def _safe(cls, v: str) -> str:
        if v and not (v.startswith("https://") or v.startswith("/") or v.startswith("mailto:")):
            raise ValueError("links must be https://, mailto: or site-relative")
        return v


class Block(CamelModel):
    id: str = Field(..., min_length=1, max_length=80)
    type: BlockType
    heading: str = Field("", max_length=240)
    body: str = Field("", max_length=20000)
    asset_refs: list[str] = Field(default_factory=list, max_length=40)
    metrics: list[Metric] = Field(default_factory=list, max_length=24)
    allocations: list[Allocation] = Field(default_factory=list, max_length=24)
    currency: str = Field("GHS", max_length=3)
    links: list[Link] = Field(default_factory=list, max_length=24)
    attribution: str = Field("", max_length=240)


class CreateIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=200)
    slug: str
    tagline: str = Field("", max_length=300)
    purpose: Purpose
    template_id: str = Field(..., min_length=1, max_length=64)
    owner: str = Field(..., min_length=1, max_length=160)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return valid_slug(v)


class UpdateIn(CamelModel):
    title: str = Field(..., min_length=1, max_length=200)
    slug: str
    tagline: str = Field("", max_length=300)
    accent_color: str = Field("", max_length=9)
    blocks: list[Block] = Field(default_factory=list, max_length=60)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return valid_slug(v)

    @field_validator("accent_color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v and not HEX.match(v):
            raise ValueError("accentColor must be a hex colour like #083755")
        return v


class AccessIn(CamelModel):
    access: Access
    access_code: str | None = Field(None, max_length=128)
    audience_stakeholder_ids: list[str] = Field(default_factory=list, max_length=200)


class ReviewIn(CamelModel):
    decision: Literal["SUBMITTED", "APPROVED", "CHANGES_REQUESTED"]
    comment: str = Field("", max_length=4000)


class ArchiveIn(CamelModel):
    archive_ref: str = Field(..., min_length=1, max_length=120)


class UnlockIn(CamelModel):
    access_code: str = Field(..., min_length=1, max_length=128)


class Analytics(CamelModel):
    views: int
    unique_visitors: int
    average_seconds: int
    downloads: int
    last_viewed_at: UtcDateTime | None


class MicrositeOut(CamelModel):
    id: UUIDStr
    slug: str
    title: str
    tagline: str
    purpose: str
    template_id: str
    status: str
    access: str
    audience_stakeholder_ids: list[str]
    accent_color: str
    owner: str
    blocks: list[Block]
    version: int
    published_version: int | None
    published_at: UtcDateTime | None
    archived_at: UtcDateTime | None
    archive_ref: str | None
    analytics: Analytics
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ReviewOut(CamelModel):
    id: UUIDStr
    microsite_id: UUIDStr
    version: int
    decision: str
    comment: str
    actor: str
    occurred_at: UtcDateTime


class TemplateOut(CamelModel):
    id: str
    name: str
    purpose: str
    description: str
    block_types: list[str]


class PublicMicrositeOut(CamelModel):
    slug: str
    title: str
    tagline: str
    purpose: str
    accent_color: str
    blocks: list[Block]
    published_at: UtcDateTime


class ViewIn(CamelModel):
    seconds: int = Field(0, ge=0, le=3 * 3600)
    new_visitor: bool = True
