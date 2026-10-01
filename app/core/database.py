"""
Database engines and sessions.

The API uses the async engine; Celery tasks use the sync engine. `get_db` does
not auto-commit: routers own their transactions (add → flush → audit → commit).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine_kwargs: dict = {"echo": settings.SQL_ECHO}
if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["pool_pre_ping"] = True

async_engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

_sync_engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True, echo=False)
SyncSessionFactory = sessionmaker(bind=_sync_engine, class_=Session, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
