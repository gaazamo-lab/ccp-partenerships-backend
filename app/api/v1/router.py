"""
Version 1 router: one module per bounded context, mounted in isolation.

Each frontend portal is served by one or two modules here, and the portals are
released separately. Importing every module at module scope would undo that: a
syntax error or a bad import anywhere means the process never starts and *all*
portals go dark together.

So each module is imported inside its own guard. A module that fails to import
is recorded and its route prefixes answer `503 MODULE_UNAVAILABLE`, naming the
module; every other module keeps serving. `GET /modules` reports the state, so a
deploy can be checked without reading logs.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleSpec:
    """One bounded context: the module to import and the portals it serves."""

    name: str
    module: str
    system: str
    portals: tuple[str, ...]
    #: Path prefixes the module owns, used for the unavailable-stub routes.
    prefixes: tuple[str, ...]


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("auth", "app.api.v1.auth", "Platform", ("all",), ("/auth",)),
    ModuleSpec(
        "users",
        "app.api.v1.users",
        "Platform",
        ("all",),
        ("/users", "/roles", "/audit-events"),
    ),
    ModuleSpec(
        "stakeholders",
        "app.api.v1.stakeholders",
        "S081",
        ("partner-portal",),
        ("/stakeholders", "/stakeholder-contacts", "/segments", "/s203"),
    ),
    ModuleSpec(
        "partnerships",
        "app.api.v1.partnerships",
        "S082",
        ("partner-portal",),
        (
            "/partnerships",
            "/partnership-obligations",
            "/partnership-reviews",
            "/partnership-renewal-alerts",
            "/partnership-audit-events",
        ),
    ),
    ModuleSpec(
        "consultations",
        "app.api.v1.consultations",
        "S088",
        ("consultation-portal",),
        ("/consultations", "/consultation-responses", "/public/consultations"),
    ),
    ModuleSpec(
        "kol",
        "app.api.v1.kol",
        "S092",
        ("partner-portal",),
        ("/kols", "/kol-engagements", "/kol-content", "/kol-mentions"),
    ),
    ModuleSpec(
        "microsites",
        "app.api.v1.microsites",
        "S091",
        ("donor-microsites",),
        ("/microsites", "/microsite-templates", "/public/microsites"),
    ),
    ModuleSpec(
        "international",
        "app.api.v1.international",
        "S083",
        ("ir-workspace",),
        ("/ir",),
    ),
    ModuleSpec(
        "travel",
        "app.api.v1.travel",
        "S084",
        ("travel-authorisation",),
        ("/travel-requests", "/travel-policy"),
    ),
)


@dataclass
class ModuleStatus:
    spec: ModuleSpec
    loaded: bool
    error: str | None = None


#: Populated by `build_v1_router`; read by `GET /modules`.
MODULE_STATUS: dict[str, ModuleStatus] = {}


def _unavailable_router(spec: ModuleSpec, reason: str) -> APIRouter:
    """Answer every path under the module's prefixes with a 503 that names it."""
    router = APIRouter()

    async def unavailable(request: Request) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "MODULE_UNAVAILABLE",
                "message": (
                    f"The {spec.system} module is not available. Other modules are unaffected; try again once it is redeployed."
                ),
                "module": spec.name,
                "system": spec.system,
                "correlationId": getattr(request.state, "correlation_id", None),
                "retryable": True,
            },
        )

    for prefix in spec.prefixes:
        router.add_api_route(
            prefix,
            unavailable,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
        router.add_api_route(
            f"{prefix}/{{rest:path}}",
            unavailable,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
    logger.error("module.unavailable module=%s system=%s reason=%s", spec.name, spec.system, reason)
    return router


def build_v1_router() -> APIRouter:
    """Import and mount every module, isolating each one's failures."""
    router = APIRouter()
    MODULE_STATUS.clear()

    for spec in MODULES:
        try:
            module = importlib.import_module(spec.module)
            router.include_router(module.router)
        except Exception as exc:  # noqa: BLE001 — one module must not stop the rest
            reason = f"{type(exc).__name__}: {exc}"
            MODULE_STATUS[spec.name] = ModuleStatus(spec, loaded=False, error=reason)
            router.include_router(_unavailable_router(spec, reason))
        else:
            MODULE_STATUS[spec.name] = ModuleStatus(spec, loaded=True)

    @router.get("/modules", include_in_schema=False)
    async def modules() -> dict[str, object]:
        """Which bounded contexts loaded, and which portals a failure affects."""
        return {
            "data": [
                {
                    "module": item.spec.name,
                    "system": item.spec.system,
                    "portals": list(item.spec.portals),
                    "loaded": item.loaded,
                    "error": item.error,
                }
                for item in MODULE_STATUS.values()
            ],
            "meta": {
                "total": len(MODULE_STATUS),
                "loaded": sum(1 for item in MODULE_STATUS.values() if item.loaded),
            },
        }

    return router


v1_router = build_v1_router()
