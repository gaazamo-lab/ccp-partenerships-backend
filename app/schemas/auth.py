"""Auth and user-management schemas."""

from __future__ import annotations

from pydantic import EmailStr, Field, field_validator

from app.core.rbac import Role
from app.schemas.common import CamelModel, UtcDateTime, UUIDStr


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class AuthUserOut(CamelModel):
    """Mirrors `AuthUser` in `@partner-crm/auth`."""

    id: UUIDStr
    email: str
    name: str
    role: str


class SessionResponse(CamelModel):
    user: AuthUserOut


class ChangePasswordRequest(CamelModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


def _validate_role(value: str) -> str:
    if value not in Role.ALL:
        raise ValueError(f"role must be one of: {', '.join(Role.ALL)}")
    return value


class UserCreate(CamelModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=200)
    role: str
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        return _validate_role(value)


class UserUpdate(CamelModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    role: str | None = None
    active: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, value: str | None) -> str | None:
        return None if value is None else _validate_role(value)


class PasswordReset(CamelModel):
    password: str = Field(..., min_length=1, max_length=256)


class UserOut(CamelModel):
    id: UUIDStr
    email: str
    name: str
    role: str
    active: bool
    locked_until: UtcDateTime | None = None
    last_login_at: UtcDateTime | None = None
    created_at: UtcDateTime


class RoleOut(CamelModel):
    role: str
    permissions: list[str]


__all__ = [
    "AuthUserOut",
    "ChangePasswordRequest",
    "LoginRequest",
    "PasswordReset",
    "RoleOut",
    "SessionResponse",
    "UserCreate",
    "UserOut",
    "UserUpdate",
]
