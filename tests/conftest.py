"""
Test fixtures.

The suite runs against `TEST_DATABASE_URL` (PostgreSQL in CI) or, when that is
unset, a throwaway SQLite file — so it also runs on a laptop without Docker.
The schema is created from the ORM metadata once per session and every table is
emptied before each test.

HTTP tests use `httpx.AsyncClient` over `ASGITransport`, which shares the test's
event loop (unlike Starlette's TestClient) and keeps cookies between calls.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

_db_file = os.path.join(tempfile.gettempdir(), "partner_crm_test.sqlite3")
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_db_file}"))
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("ALLOWED_ORIGINS", "http://testserver,http://localhost:5175")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import app.models  # noqa: E402,F401 — registers every model
from app.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.users import User  # noqa: E402

PASSWORD = "Correct-Horse-9"


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await async_engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    async with AsyncSessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
    yield


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as http:
        yield http


async def make_user(email: str, role: str, name: str | None = None, password: str = PASSWORD) -> User:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            return existing
        user = User(email=email, name=name or email.split("@")[0].title(), role=role, password_hash=hash_password(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def login_as(http: AsyncClient, email: str, role: str, name: str | None = None) -> User:
    user = await make_user(email, role, name)
    response = await http.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return user


@pytest.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    await login_as(client, "admin@clet.gov.gh", "CRM Administrator", "Ama Admin")
    return client
