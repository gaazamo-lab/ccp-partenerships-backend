"""
Partner CRM API — FastAPI application.

Serves the CCP Partnerships frontends in the partner-crm monorepo:
S081 Stakeholder CRM, S082 MOU tracker, S083 International Relations,
S088 Consultations, S091 Donor Microsites and S092 KOL Tracker.

Routes live under `settings.API_PREFIX` (default `/api/v1`) so the frontends can
reach them same-origin through their dev proxy or the production gateway.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import v1_router
from app.core.config import settings
from app.core.database import async_engine
from app.core.errors import register_exception_handlers
from app.core.middleware import OriginCheckMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "startup service=%s env=%s prefix=%s db=%s",
        settings.SERVICE_NAME,
        settings.ENV,
        settings.API_PREFIX,
        settings.DATABASE_URL.split("@")[-1],
    )
    if not settings.SESSION_COOKIE_SECURE:
        logger.warning("startup.insecure_cookie SESSION_COOKIE_SECURE=false — local development only")
    yield
    await async_engine.dispose()


app = FastAPI(
    title="Partner CRM API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=f"{settings.API_PREFIX}/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url=f"{settings.API_PREFIX}/openapi.json" if settings.DEBUG else None,
)

# Starlette runs middleware in reverse registration order: context first.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(v1_router, prefix=settings.API_PREFIX)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness: the process is up. Touches nothing external."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Readiness: the database answers within two seconds."""

    async def _ping() -> None:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=2)
    except Exception as exc:  # noqa: BLE001 — report class only, never details
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": type(exc).__name__})
    return {"status": "ready"}
