"""
Application settings, loaded from the environment (and `.env` in development).

Dependencies call `get_settings()` per request rather than holding the module
level `settings`, so tests can `get_settings.cache_clear()` and re-read the
environment.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PLACEHOLDER_SECRET_KEY = "change-me-in-production"  # noqa: S105  # nosec B105 — refused in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Core ──
    SERVICE_NAME: str = "partner-crm-api"
    ENV: Literal["dev", "staging", "production"] = "dev"
    DEBUG: bool = False
    SQL_ECHO: bool = False  # log every SQL statement (very verbose)
    SECRET_KEY: str = PLACEHOLDER_SECRET_KEY
    API_PREFIX: str = "/api/v1"

    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/partner_crm"

    @property
    def SYNC_DATABASE_URL(self) -> str:  # noqa: N802 — mirrors the env-var naming
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://").replace(
            "sqlite+aiosqlite://", "sqlite://"
        )

    # ── Queue ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Sessions (email + password, HTTP-only cookie) ──
    SESSION_COOKIE_NAME: str = "pcrm_session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: Literal["lax", "strict"] = "lax"
    SESSION_IDLE_MINUTES: int = Field(120, ge=5, le=24 * 60)
    SESSION_ABSOLUTE_HOURS: int = Field(12, ge=1, le=72)

    # ── Login protection ──
    LOGIN_MAX_FAILED_ATTEMPTS: int = Field(5, ge=1, le=50)
    LOGIN_LOCKOUT_MINUTES: int = Field(15, ge=1, le=24 * 60)
    PASSWORD_MIN_LENGTH: int = Field(12, ge=8, le=128)

    # ── CSRF: state-changing requests must come from one of these origins ──
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5175",
            "http://localhost:5176",
            "http://localhost:5177",
            "http://localhost:5178",
            "http://localhost:5179",
        ]
    )

    # ── Bootstrap administrator (used by scripts/seed.py only) ──
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@clet.gov.gh"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    # ── Integrations (outbox relays). Empty URL = not connected; rows stay pending. ──
    S074_COMMS_URL: str = ""
    S074_API_KEY: str = ""
    S203_SCREENING_URL: str = ""
    S203_API_KEY: str = ""
    S204_AUDIT_URL: str = ""
    S011_GIFTS_URL: str = ""
    S225_ANALYTICS_URL: str = ""
    INTEGRATION_TIMEOUT_SECONDS: float = Field(10.0, gt=0, le=120)
    OUTBOX_MAX_ATTEMPTS: int = Field(8, ge=1, le=100)

    # ── S082 renewal alerts ──
    RENEWAL_ALERT_DEFAULT_RECIPIENTS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["partnerships@clet.gov.gh", "registrar@clet.gov.gh"]
    )

    # ── Public endpoints ──
    PUBLIC_SUBMISSIONS_PER_MINUTE: int = Field(20, ge=1, le=10_000)
    MICROSITE_UNLOCK_ATTEMPTS_PER_MINUTE: int = Field(10, ge=1, le=1000)

    @field_validator("ALLOWED_ORIGINS", "RENEWAL_ALERT_DEFAULT_RECIPIENTS", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> Settings:
        # RuntimeError (not ValueError) so pydantic does not echo env values back.
        if self.ENV == "production":
            if self.SECRET_KEY == PLACEHOLDER_SECRET_KEY or len(self.SECRET_KEY) < 32:
                raise RuntimeError("SECRET_KEY must be a strong, non-placeholder value in production.")
            if not self.SESSION_COOKIE_SECURE:
                raise RuntimeError("SESSION_COOKIE_SECURE must be true in production.")
            if self.DATABASE_URL.startswith("sqlite"):
                raise RuntimeError("SQLite is for local tests only; use PostgreSQL in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
