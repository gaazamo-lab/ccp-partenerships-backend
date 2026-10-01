"""
S091 Donor / Annual-Report Microsite Builder.

Blocks are one JSON document per microsite (edited as a whole in the builder).
The public site serves the snapshot taken at publish time (`published_blocks`),
so later draft edits never reach donors before re-approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class MicrositeStatus:
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    EDITABLE = [DRAFT, CHANGES_REQUESTED, APPROVED]


class MicrositeTemplate(Base):
    __tablename__ = "ms_template"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    block_types: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)


class Microsite(Base):
    __tablename__ = "ms_microsite"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    tagline: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[str] = mapped_column(String(64), ForeignKey("ms_template.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=MicrositeStatus.DRAFT, index=True)
    access: Mapped[str] = mapped_column(String(16), nullable=False, default="PUBLIC")
    access_code_hash: Mapped[str | None] = mapped_column(String(255))
    audience_stakeholder_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    accent_color: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(160), nullable=False)
    blocks: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_by: Mapped[str | None] = mapped_column(String(64))
    published_version: Mapped[int | None] = mapped_column(Integer)
    published_blocks: Mapped[list | None] = mapped_column(JSONType)
    published_title: Mapped[str | None] = mapped_column(String(200))
    published_tagline: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_ref: Mapped[str | None] = mapped_column(String(120))
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_visitors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class MicrositeReview(Base):
    __tablename__ = "ms_review"

    id: Mapped[uuid.UUID] = uuid_pk()
    microsite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ms_microsite.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    occurred_at: Mapped[datetime] = created_at_column()


# Reference data, seeded by migration 0001 and scripts/seed.py (idempotent).
DEFAULT_TEMPLATES = [
    {
        "id": "tpl-annual-report",
        "name": "Annual report portal",
        "purpose": "ANNUAL_REPORT",
        "description": "Year in review with headline metrics, fund utilisation, stories and downloadable reports.",
        "block_types": ["HERO", "METRICS", "RICH_TEXT", "FUND_UTILISATION", "STORY", "GALLERY", "DOWNLOADS"],
    },
    {
        "id": "tpl-donor-impact",
        "name": "Donor impact report",
        "purpose": "DONOR_IMPACT",
        "description": "Show a donor how their funds were used and what changed for students.",
        "block_types": ["HERO", "FUND_UTILISATION", "METRICS", "STORY", "QUOTE", "CALL_TO_ACTION"],
    },
    {
        "id": "tpl-campaign",
        "name": "Fundraising campaign",
        "purpose": "CAMPAIGN",
        "description": "A focused appeal with a clear goal and call to action.",
        "block_types": ["HERO", "RICH_TEXT", "METRICS", "QUOTE", "CALL_TO_ACTION"],
    },
    {
        "id": "tpl-event-hub",
        "name": "Conference & event hub",
        "purpose": "EVENT_HUB",
        "description": "Programme, speakers, gallery and resources for a CLET event.",
        "block_types": ["HERO", "RICH_TEXT", "GALLERY", "DOWNLOADS", "CALL_TO_ACTION"],
    },
    {
        "id": "tpl-thought-leadership",
        "name": "Thought-leadership series",
        "purpose": "THOUGHT_LEADERSHIP",
        "description": "Essays and perspectives from CLET and its thought leaders.",
        "block_types": ["HERO", "RICH_TEXT", "QUOTE", "STORY", "CALL_TO_ACTION"],
    },
]
