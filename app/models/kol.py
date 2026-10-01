"""
S092 Influencer / KOL & Thought-Leader Tracker. Profiles are extension records
anchored to S081 (`stakeholder_id`) or S034 (`alumni_ref`).
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, created_at_column, updated_at_column, uuid_pk


class KolProfile(Base):
    __tablename__ = "kol_profile"

    id: Mapped[uuid.UUID] = uuid_pk()
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    honorific: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    organisation: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    stakeholder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("crm_stakeholder.id", ondelete="SET NULL"), index=True
    )
    alumni_ref: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expertise: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    influence_areas: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    influence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    relationship_owner: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PROSPECT")
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, default="NONE")
    risk_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class KolEngagement(Base):
    __tablename__ = "kol_engagement"

    id: Mapped[uuid.UUID] = uuid_pk()
    kol_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("kol_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="PLANNED")
    scheduled_for: Mapped[dt.date | None] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(160), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    participation: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class KolContent(Base):
    __tablename__ = "kol_content"

    id: Mapped[uuid.UUID] = uuid_pk()
    kol_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("kol_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False, default="COMMISSIONED")
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    draft_ref: Mapped[str | None] = mapped_column(String(120))
    reviewer: Mapped[str | None] = mapped_column(String(200))
    review_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cms_ref: Mapped[str | None] = mapped_column(String(120))
    published_url: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class KolMediaMention(Base):
    __tablename__ = "kol_media_mention"

    id: Mapped[uuid.UUID] = uuid_pk()
    kol_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("kol_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("kol_content.id", ondelete="SET NULL"))
    outlet: Mapped[str] = mapped_column(String(160), nullable=False)
    headline: Mapped[str] = mapped_column(String(400), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    published_at: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reach: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sentiment: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="MANUAL")
