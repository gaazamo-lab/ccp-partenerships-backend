"""
Shared schema building blocks.

- `CamelModel`: every request/response model speaks camelCase JSON (the
  frontend contracts in `packages/types`) while Python code stays snake_case.
- `Envelope` / `PaginatedEnvelope`: the `ApiEnvelope<T>` / `PaginatedEnvelope<T>`
  response shapes the frontend expects.
- `UUIDStr`, `UtcDateTime`: coerce ORM values (UUID objects, naive SQLite
  datetimes) into the strings the contracts declare.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


def _stringify_uuid(value: Any) -> Any:
    return str(value) if isinstance(value, uuid.UUID) else value


def _utc_iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


UUIDStr = Annotated[str, BeforeValidator(_stringify_uuid)]
UtcDateTime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        str_strip_whitespace=True,
    )


T = TypeVar("T")


class Envelope(CamelModel, Generic[T]):
    success: bool = True
    data: T
    message: str | None = None


class PageMeta(CamelModel):
    count: int
    page: int
    page_size: int
    next: str | None = None
    previous: str | None = None


class PaginatedEnvelope(CamelModel, Generic[T]):
    success: bool = True
    data: list[T]
    meta: PageMeta
    message: str | None = None


def ok(data: Any, message: str | None = None) -> dict[str, Any]:
    """Wrap a payload in the `ApiEnvelope` shape (validated by the route's response_model)."""
    return {"success": True, "data": data, "message": message}


def paginated(data: list[Any], *, count: int, page: int, page_size: int) -> dict[str, Any]:
    has_next = page * page_size < count
    return {
        "success": True,
        "data": data,
        "meta": {
            "count": count,
            "page": page,
            "pageSize": page_size,
            "next": str(page + 1) if has_next else None,
            "previous": str(page - 1) if page > 1 else None,
        },
    }
