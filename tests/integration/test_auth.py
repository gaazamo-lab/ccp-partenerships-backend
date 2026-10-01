"""Email + password sessions, lockout, CSRF origin checks and RBAC."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import PASSWORD, login_as, make_user


async def test_login_sets_http_only_cookie_and_session_resolves(client: AsyncClient):
    await make_user("officer@clet.gov.gh", "Partnerships Officer", "Kofi Officer")

    response = await client.post("/api/v1/auth/login", json={"email": "Officer@CLET.gov.gh", "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["user"] == {
        "id": response.json()["user"]["id"],
        "email": "officer@clet.gov.gh",
        "name": "Kofi Officer",
        "role": "Partnerships Officer",
    }
    cookie = response.headers["set-cookie"].lower()
    assert "pcrm_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie

    session = await client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["email"] == "officer@clet.gov.gh"


async def test_wrong_password_and_unknown_email_look_identical(client: AsyncClient):
    await make_user("officer@clet.gov.gh", "Partnerships Officer")

    wrong = await client.post("/api/v1/auth/login", json={"email": "officer@clet.gov.gh", "password": "nope-nope"})
    unknown = await client.post("/api/v1/auth/login", json={"email": "ghost@clet.gov.gh", "password": "nope-nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]
    assert wrong.json()["correlationId"]


async def test_account_locks_after_repeated_failures(client: AsyncClient):
    await make_user("officer@clet.gov.gh", "Partnerships Officer")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "officer@clet.gov.gh", "password": "bad-password"})

    locked = await client.post("/api/v1/auth/login", json={"email": "officer@clet.gov.gh", "password": PASSWORD})

    assert locked.status_code == 401
    assert locked.json()["code"] == "ACCOUNT_LOCKED"


async def test_logout_revokes_the_session(client: AsyncClient):
    await login_as(client, "officer@clet.gov.gh", "Partnerships Officer")

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_state_change_from_foreign_origin_is_rejected(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "a@clet.gov.gh", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_ORIGIN_REJECTED"


async def test_user_admin_requires_permission_and_enforces_password_policy(client: AsyncClient):
    await login_as(client, "officer@clet.gov.gh", "Partnerships Officer")
    assert (await client.get("/api/v1/users")).status_code == 403

    await client.post("/api/v1/auth/logout")
    await login_as(client, "dti@clet.gov.gh", "System Administrator")
    weak = await client.post(
        "/api/v1/users", json={"email": "new@clet.gov.gh", "name": "New", "role": "Auditor", "password": "short"}
    )
    assert weak.status_code == 422
    created = await client.post(
        "/api/v1/users",
        json={"email": "new@clet.gov.gh", "name": "New Auditor", "role": "Auditor", "password": "Str0ng-Password!"},
    )
    assert created.status_code == 201
    assert created.json()["data"]["role"] == "Auditor"
    assert "passwordHash" not in created.json()["data"]


async def test_audit_chain_is_recorded_and_intact(client: AsyncClient):
    await login_as(client, "auditor@clet.gov.gh", "Auditor")
    feed = await client.get("/api/v1/audit-events")
    assert feed.status_code == 200
    assert feed.json()["data"][0]["action"] == "auth.login_succeeded"
    integrity = await client.get("/api/v1/audit-events/integrity")
    assert integrity.json()["data"]["intact"] is True
