"""S092: profile rules, S081 link, engagement and content stage machines, media reach."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import login_as

BASE = "/api/v1"

PROFILE = {
    "fullName": "Justice Ama Serwaa",
    "honorific": "Hon.",
    "category": "RETIRED_JUDGE",
    "organisation": "Supreme Court (retd.)",
    "position": "Former Justice",
    "email": "ama.serwaa@example.com",
    "expertise": ["Constitutional law", "constitutional law", "Ethics"],
    "influenceAreas": ["Judicial reform"],
    "influenceLevel": "NATIONAL",
    "availability": "LIMITED",
    "relationshipOwner": "Nana Asante",
    "riskLevel": "NONE",
}


async def _kol(http: AsyncClient, **overrides) -> dict:
    response = await http.post(f"{BASE}/kols", json={**PROFILE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_profile_rules_and_stakeholder_link(admin_client: AsyncClient):
    kol = await _kol(admin_client)
    assert kol["expertise"] == ["Constitutional law", "Ethics"]
    assert (await admin_client.post(f"{BASE}/kols", json={**PROFILE, "fullName": "Other"})).status_code == 409
    risky = await admin_client.post(f"{BASE}/kols", json={**PROFILE, "email": "", "riskLevel": "HIGH"})
    assert risky.status_code == 422
    missing_link = await admin_client.post(
        f"{BASE}/kols", json={**PROFILE, "email": "", "stakeholderId": "00000000-0000-0000-0000-000000000009"}
    )
    assert missing_link.status_code == 422

    gba = (await admin_client.post(f"{BASE}/stakeholders", json={"name": "GBA", "category": "Professional body"})).json()["data"]
    linked = await _kol(admin_client, email="", fullName="Kwame Adjei", stakeholderId=gba["id"])
    listed = (await admin_client.get(f"{BASE}/kols", params={"stakeholderId": gba["id"]})).json()["data"]
    assert [k["id"] for k in listed] == [linked["id"]]


async def test_engagement_pipeline_and_participation(admin_client: AsyncClient):
    kol = await _kol(admin_client)
    created = await admin_client.post(
        f"{BASE}/kols/{kol['id']}/engagements",
        json={"type": "PANEL", "title": "Bar week panel", "owner": "Nana", "scheduledFor": "2026-11-02"},
    )
    engagement = created.json()["data"]
    skip = await admin_client.post(f"{BASE}/kol-engagements/{engagement['id']}/stage", json={"stage": "COMPLETED"})
    assert skip.status_code == 409
    early = await admin_client.put(
        f"{BASE}/kol-engagements/{engagement['id']}/participation",
        json={"attended": True, "outputs": "", "feedback": "", "contributionScore": 4},
    )
    assert early.status_code == 409
    for stage in ("INVITED", "CONFIRMED"):
        assert (
            await admin_client.post(f"{BASE}/kol-engagements/{engagement['id']}/stage", json={"stage": stage})
        ).status_code == 200
    recorded = await admin_client.put(
        f"{BASE}/kol-engagements/{engagement['id']}/participation",
        json={"attended": True, "outputs": "Keynote on ethics", "feedback": "Strong", "contributionScore": 5},
    )
    data = recorded.json()["data"]
    assert data["stage"] == "COMPLETED" and data["participation"]["recordedBy"] == "Ama Admin"
    assert (await admin_client.get(f"{BASE}/kols/{kol['id']}")).json()["data"]["status"] == "ACTIVE"


async def test_content_workflow_requires_evidence_at_each_step(admin_client: AsyncClient):
    kol = await _kol(admin_client)
    content = (
        await admin_client.post(f"{BASE}/kols/{kol['id']}/content", json={"title": "Why CLE matters", "contentType": "OP_ED"})
    ).json()["data"]
    url = f"{BASE}/kol-content/{content['id']}/stage"
    assert (await admin_client.post(url, json={"stage": "DRAFT_SUBMITTED"})).status_code == 422
    assert (await admin_client.post(url, json={"stage": "DRAFT_SUBMITTED", "draftRef": "S003-D1"})).status_code == 200
    assert (await admin_client.post(url, json={"stage": "IN_REVIEW"})).status_code == 200
    assert (await admin_client.post(url, json={"stage": "CHANGES_REQUESTED"})).status_code == 422
    assert (await admin_client.post(url, json={"stage": "CHANGES_REQUESTED", "reviewNotes": "Tighten intro"})).status_code == 200
    for step in ({"stage": "DRAFT_SUBMITTED"}, {"stage": "IN_REVIEW"}, {"stage": "APPROVED"}):
        assert (await admin_client.post(url, json=step)).status_code == 200
    assert (await admin_client.post(url, json={"stage": "PUBLISHED"})).status_code == 422
    published = await admin_client.post(
        url, json={"stage": "PUBLISHED", "publishedUrl": "https://clet.gov.gh/news/cle", "cmsRef": "S076-881"}
    )
    assert published.json()["data"]["publishedAt"] is not None

    mention = await admin_client.post(
        f"{BASE}/kols/{kol['id']}/mentions",
        json={
            "contentId": content["id"],
            "outlet": "Daily Graphic",
            "headline": "Retired justice on CLE",
            "url": "",
            "publishedAt": "2026-09-20",
            "reach": 120000,
            "sentiment": "POSITIVE",
        },
    )
    assert mention.json()["data"]["source"] == "MANUAL"


async def test_archived_kols_cannot_be_engaged_and_viewers_are_read_only(admin_client: AsyncClient):
    kol = await _kol(admin_client, status="ARCHIVED")
    refused = await admin_client.post(f"{BASE}/kols/{kol['id']}/engagements", json={"type": "OP_ED", "title": "x", "owner": "n"})
    assert refused.status_code == 409

    await admin_client.post(f"{BASE}/auth/logout")
    await login_as(admin_client, "exec@clet.gov.gh", "Executive Viewer")
    assert (await admin_client.get(f"{BASE}/kols")).status_code == 200
    assert (await admin_client.post(f"{BASE}/kols", json=PROFILE)).status_code == 403
