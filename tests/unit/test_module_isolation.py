"""
One broken bounded context must not take the other portals down with it.

The five frontends are released separately, so a bad deploy of (say) S084 has to
degrade to "S084 is unavailable" rather than a process that will not start.
These tests drive `build_v1_router` with a module that cannot be imported and
check what survives.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import router as router_module
from app.api.v1.router import MODULES, ModuleSpec, build_v1_router
from app.core.errors import register_exception_handlers


@pytest.fixture
def broken_travel(monkeypatch):
    """Replace the S084 spec with one pointing at a module that does not exist."""
    patched = tuple(
        ModuleSpec(
            name=spec.name,
            module="app.api.v1._does_not_exist",
            system=spec.system,
            portals=spec.portals,
            prefixes=spec.prefixes,
        )
        if spec.name == "travel"
        else spec
        for spec in MODULES
    )
    monkeypatch.setattr(router_module, "MODULES", patched)
    return patched


def _app() -> FastAPI:
    """A test app wired like `main.py`, so domain errors become responses."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_v1_router(), prefix="/api/v1")
    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    )


async def test_a_broken_module_does_not_stop_the_others(broken_travel):
    app = _app()

    async with await _client(app) as http:
        registry = (await http.get("/api/v1/modules")).json()
        states = {row["module"]: row["loaded"] for row in registry["data"]}

        # Only S084 is down.
        assert states["travel"] is False
        assert all(loaded for name, loaded in states.items() if name != "travel")
        assert registry["meta"]["loaded"] == registry["meta"]["total"] - 1

        travel = next(row for row in registry["data"] if row["module"] == "travel")
        assert travel["error"]
        assert travel["portals"] == ["travel-authorisation"]


async def test_the_broken_module_answers_503_naming_itself(broken_travel):
    app = _app()

    async with await _client(app) as http:
        for path in ("/api/v1/travel-requests", "/api/v1/travel-requests/any-id", "/api/v1/travel-policy"):
            response = await http.get(path)
            assert response.status_code == 503, path
            body = response.json()
            assert body["code"] == "MODULE_UNAVAILABLE"
            assert body["system"] == "S084"
            # Retryable, so the client can show "try again" rather than a dead end.
            assert body["retryable"] is True

        # A write to the broken module is refused the same way, not 404 or 500.
        assert (await http.post("/api/v1/travel-requests", json={})).status_code == 503


async def test_other_portals_stay_reachable_while_one_is_broken(broken_travel):
    """S081/S082/S083/S088/S091 must still answer while S084 is down."""
    app = _app()

    async with await _client(app) as http:
        for path in (
            "/api/v1/stakeholders",
            "/api/v1/partnerships",
            "/api/v1/consultations",
            "/api/v1/microsites",
            "/api/v1/ir/engagements",
        ):
            response = await http.get(path)
            # 401 means the request reached the real module and was refused for
            # want of a session — not the 503 stub, and not a missing route.
            assert response.status_code == 401, (path, response.status_code)

        # The public routes of the healthy modules need no session at all.
        assert (await http.get("/api/v1/public/consultations")).status_code == 200


async def test_every_module_loads_in_the_normal_build():
    """The guard must not be hiding a real failure in the shipped configuration."""
    build_v1_router()
    assert all(item.loaded for item in router_module.MODULE_STATUS.values()), {
        name: item.error for name, item in router_module.MODULE_STATUS.items() if not item.loaded
    }
