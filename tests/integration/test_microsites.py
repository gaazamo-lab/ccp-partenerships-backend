"""S091: template seeding, edit/approval versioning, four-eyes, publish snapshot, access control."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.rate_limit import reset_local
from app.main import app
from app.models.microsites import DEFAULT_TEMPLATES, MicrositeTemplate
from tests.conftest import PASSWORD, make_user

BASE = "/api/v1"


async def _seed_templates() -> None:
    async with AsyncSessionLocal() as session:
        for template in DEFAULT_TEMPLATES:
            session.add(MicrositeTemplate(**template))
        await session.commit()


async def _as(http: AsyncClient, email: str, role: str) -> None:
    await http.post(f"{BASE}/auth/logout")
    await make_user(email, role, email.split("@")[0].title())
    assert (await http.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200


async def _create(http: AsyncClient) -> dict:
    response = await http.post(
        f"{BASE}/microsites",
        json={
            "title": "2026 Annual Report",
            "slug": "annual-report-2026",
            "tagline": "A year of firsts",
            "purpose": "ANNUAL_REPORT",
            "templateId": "tpl-annual-report",
            "owner": "Efua Owusu",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _approved(http: AsyncClient) -> dict:
    site = await _create(http)
    await http.post(f"{BASE}/microsites/{site['id']}/reviews", json={"decision": "SUBMITTED", "comment": ""})
    await _as(http, "rmf@clet.gov.gh", "RMF Reviewer")
    approved = await http.post(
        f"{BASE}/microsites/{site['id']}/reviews", json={"decision": "APPROVED", "comment": "Figures checked"}
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


async def test_create_seeds_blocks_from_template(admin_client: AsyncClient):
    await _seed_templates()
    site = await _create(admin_client)
    assert [b["type"] for b in site["blocks"]][:2] == ["HERO", "METRICS"]
    assert site["blocks"][0]["heading"] == "2026 Annual Report"
    assert (
        await admin_client.post(
            f"{BASE}/microsites",
            json={
                "title": "Dup",
                "slug": "annual-report-2026",
                "purpose": "CAMPAIGN",
                "templateId": "tpl-campaign",
                "owner": "x",
            },
        )
    ).status_code == 409


async def test_submitter_cannot_approve_and_edits_reset_approval(admin_client: AsyncClient):
    await _seed_templates()
    site = await _create(admin_client)
    await admin_client.post(f"{BASE}/microsites/{site['id']}/reviews", json={"decision": "SUBMITTED", "comment": ""})
    self_approve = await admin_client.post(
        f"{BASE}/microsites/{site['id']}/reviews", json={"decision": "APPROVED", "comment": ""}
    )
    assert self_approve.status_code == 409 and self_approve.json()["code"] == "FOUR_EYES"

    await _as(admin_client, "rmf@clet.gov.gh", "RMF Reviewer")
    approved = (
        await admin_client.post(f"{BASE}/microsites/{site['id']}/reviews", json={"decision": "APPROVED", "comment": ""})
    ).json()["data"]
    assert approved["status"] == "APPROVED"

    await _as(admin_client, "content@clet.gov.gh", "Content Manager")
    blocks = approved["blocks"]
    blocks[1]["metrics"] = [{"label": "Students enrolled", "value": "4,210", "sourceRef": "S225:intake-2026"}]
    edited = await admin_client.put(
        f"{BASE}/microsites/{site['id']}",
        json={"title": approved["title"], "slug": approved["slug"], "tagline": "", "accentColor": "#083755", "blocks": blocks},
    )
    assert edited.json()["data"]["status"] == "DRAFT" and edited.json()["data"]["version"] == 2
    bad_source = await admin_client.put(
        f"{BASE}/microsites/{site['id']}",
        json={
            "title": "x",
            "slug": approved["slug"],
            "blocks": [{**blocks[1], "metrics": [{"label": "a", "value": "1", "sourceRef": "spreadsheet"}]}],
        },
    )
    assert bad_source.status_code == 422


async def test_publish_serves_snapshot_and_password_unlock_sets_cookie(admin_client: AsyncClient):
    reset_local()
    await _seed_templates()
    site = await _approved(admin_client)
    await _as(admin_client, "pm@clet.gov.gh", "CCP Partnerships Manager")
    no_code = await admin_client.put(f"{BASE}/microsites/{site['id']}/access", json={"access": "PASSWORD"})
    assert no_code.status_code == 422
    await admin_client.put(f"{BASE}/microsites/{site['id']}/access", json={"access": "PASSWORD", "accessCode": "donor-2026"})
    published = await admin_client.post(f"{BASE}/microsites/{site['id']}/publish")
    assert published.json()["data"]["publishedVersion"] == 1

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers={"Origin": "http://testserver"}
    ) as visitor:
        locked = await visitor.get(f"{BASE}/public/microsites/annual-report-2026")
        assert locked.status_code == 401 and locked.json()["code"] == "MICROSITE_LOCKED"
        assert (
            await visitor.post(f"{BASE}/public/microsites/annual-report-2026/unlock", json={"accessCode": "wrong-code"})
        ).status_code == 401
        unlocked = await visitor.post(f"{BASE}/public/microsites/annual-report-2026/unlock", json={"accessCode": "donor-2026"})
        assert unlocked.status_code == 200 and "accessCode" not in unlocked.text
        assert (await visitor.get(f"{BASE}/public/microsites/annual-report-2026")).status_code == 200
        assert (await visitor.post(f"{BASE}/public/microsites/annual-report-2026/views", json={"seconds": 40})).status_code == 204
        assert (await visitor.get(f"{BASE}/public/microsites")).json()["data"] == []  # restricted sites are not listed

    # Changing the code revokes earlier unlocks.
    await admin_client.put(f"{BASE}/microsites/{site['id']}/access", json={"access": "PASSWORD", "accessCode": "new-code-2027"})
    stats = (await admin_client.get(f"{BASE}/microsites/{site['id']}")).json()["data"]["analytics"]
    assert stats["views"] == 1 and stats["averageSeconds"] == 40


async def test_archive_requires_reference_and_is_terminal(admin_client: AsyncClient):
    await _seed_templates()
    site = await _approved(admin_client)
    assert (await admin_client.post(f"{BASE}/microsites/{site['id']}/archive", json={})).status_code == 422
    archived = await admin_client.post(f"{BASE}/microsites/{site['id']}/archive", json={"archiveRef": "S003-ARC-9"})
    assert archived.json()["data"]["status"] == "ARCHIVED"
    assert (await admin_client.post(f"{BASE}/microsites/{site['id']}/publish")).status_code == 409
