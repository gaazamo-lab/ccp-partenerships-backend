"""Alembic environment: async engine, URL from app settings, all models registered."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 — registers every ORM model for autogenerate
from alembic import context
from app.core.config import get_settings
from app.models.base import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().DATABASE_URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
