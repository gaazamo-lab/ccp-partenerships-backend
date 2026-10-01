"""S081: register, duplicates, screening gate, consent, engagements, live segments, RBAC."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.audit_events import AuditAction
from app.core.config import get_settings
from app.models.audit import AuditEvent, OutboxEvent
from tests.conftest import login_as

BASE = "/api/v1"

GBA = {
    "name": "Ghana Bar Association",
    "shortName": "GBA",
    "category": "Professional body",
    "owner": "Nana Asante",
    "location": "Accra",
    "website": "https://www.ghanabar.org",
    "description": "National professional association.",
}
DONOR = {**GBA, "name": "Legal Futures Foundation", "shortName": "", "category": "Donor", "website": "legalfutures.org"}


async def _create(http: AsyncClient, body: dict) -> dict:
    response = await http.post(f"{BASE}/stakeholders", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_returns_contract_shape_and_regulated_starts_screening_pending(admin_client: AsyncClient):
    gba = await _create(admin_client, GBA)
    donor = await _create(admin_client, DONOR)

    assert gba["status"] == "Active" and gba["pipelineStage"] == "Prospect"
    assert gba["lastEngagement"] == "Not yet engaged" and gba["contacts"] == []
    assert donor["status"] == "Screening pending"
    assert donor["shortName"] == "LFF"


async def test_duplicate_by_name_or_website_needs_a_reason_to_override(admin_client: AsyncClient):
    await _create(admin_client, GBA)
    clash = await admin_client.post(f"{BASE}/stakeholders", json={**GBA, "name": "GBA National", "website": "ghanabar.org/"})
    assert clash.status_code == 409
    assert clash.json()["code"] == "DUPLICATE_STAKEHOLDER" and clash.json()["duplicateName"] == "Ghana Bar Association"

    no_reason = await admin_client.post(f"{BASE}/stakeholders", json={**GBA, "force": True})
    assert no_reason.status_code == 422
    forced = await admin_client.post(f"{BASE}/stakeholders", json={**GBA, "force": True, "overrideReason": "Regional chapter"})
    assert forced.status_code == 201


async def test_client_supplied_id_is_kept(admin_client: AsyncClient):
    wanted = "7b0f2a4e-3c1d-4f7a-9d2b-1a2b3c4d5e6f"
    created = await _create(admin_client, {**GBA, "id": wanted})
    assert created["id"] == wanted


async def test_individual_learner_domains_are_rejected(admin_client: AsyncClient):
    response = await admin_client.post(f"{BASE}/stakeholders", json={**GBA, "website": "kofi.students.gsl.edu.gh"})
    assert response.status_code == 422
    assert response.json()["code"] == "INDIVIDUAL_RECORD_REJECTED"


async def test_screening_gate_blocks_engagement_until_cleared(admin_client: AsyncClient):
    donor = await _create(admin_client, DONOR)
    with_contact = await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/contacts",
        json={
            "name": "Abena Mensah",
            "role": "Director",
            "email": "abena@legalfutures.org",
            "consent": "Not recorded",
            "regulated": False,
        },
    )
    contact = with_contact.json()["data"]["contacts"][0]
    assert contact["screening"] == "Pending"  # regulated by category even though the form said no

    blocked = await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/engagements", json={"type": "Meeting", "title": "Intro"}
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "SCREENING_REQUIRED"

    needs_notes = await admin_client.post(f"{BASE}/stakeholder-contacts/{contact['id']}/screening", json={"outcome": "Rejected"})
    assert needs_notes.status_code == 422

    cleared = await admin_client.post(
        f"{BASE}/stakeholder-contacts/{contact['id']}/screening", json={"outcome": "Cleared", "caseRef": "S203-2026-114"}
    )
    body = cleared.json()["data"]
    assert body["status"] == "Active"
    assert body["contacts"][0]["screeningRecord"]["reviewer"] == "Ama Admin"

    logged = await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/engagements",
        json={"type": "Call", "title": "Intro call", "summary": "Scope", "date": "2026-09-01"},
    )
    assert logged.status_code == 201
    assert logged.json()["data"]["lastEngagement"] == "2026-09-01"


async def test_s203_queue_callback_and_activity_are_authenticated_idempotent_and_audited(
    admin_client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(get_settings(), "S203_API_KEY", "s203-test-key")
    donor = await _create(admin_client, DONOR)
    created = await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/contacts",
        json={
            "name": "Abena Mensah",
            "role": "Director",
            "email": "abena@legalfutures.org",
            "consent": "Not recorded",
            "regulated": False,
        },
    )
    contact_id = created.json()["data"]["contacts"][0]["id"]

    unauthenticated = await admin_client.get(f"{BASE}/s203/screening-cases")
    assert unauthenticated.status_code == 401
    headers = {"X-Api-Key": "s203-test-key"}
    queue = await admin_client.get(f"{BASE}/s203/screening-cases?status=Pending", headers=headers)
    assert queue.status_code == 200
    case = queue.json()["data"][0]
    assert case["caseId"] == contact_id
    assert case["stakeholder"]["name"] == DONOR["name"]
    assert case["subject"]["email"] == "abena@legalfutures.org"

    decision = {"eventId": "s203-event-001", "outcome": "Cleared", "notes": "No match", "caseRef": "S203-2026-114"}
    accepted = await admin_client.post(f"{BASE}/s203/screening-cases/{contact_id}/decision", json=decision, headers=headers)
    repeated = await admin_client.post(f"{BASE}/s203/screening-cases/{contact_id}/decision", json=decision, headers=headers)
    assert accepted.status_code == repeated.status_code == 200
    assert accepted.json()["data"]["status"] == "Cleared"
    assert accepted.json()["data"]["decision"]["reviewer"] == "S203 Screening"

    activities = await admin_client.get(f"{BASE}/s203/screening-cases/{contact_id}/activities", headers=headers)
    assert [item["action"] for item in activities.json()["data"]] == [
        AuditAction.CONTACT_SCREENING_REQUESTED,
        AuditAction.S203_SCREENING_DECISION_RECEIVED,
    ]

    queued = await db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.target_system == "S203", OutboxEvent.idempotency_key == f"s203-screening:{contact_id}"
        )
    )
    assert queued is not None and queued.payload["subject"]["name"] == "Abena Mensah"
    decision_events = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.resource_id == contact_id,
            AuditEvent.action == AuditAction.S203_SCREENING_DECISION_RECEIVED,
        )
    )
    assert decision_events == 1


async def test_contact_email_is_unique_and_consent_needs_date_and_channel(admin_client: AsyncClient):
    gba = await _create(admin_client, GBA)
    contact_body = {
        "name": "Ama Owusu",
        "role": "Secretary",
        "email": "ama@ghanabar.org",
        "consent": "Not recorded",
        "regulated": False,
    }
    first = await admin_client.post(f"{BASE}/stakeholders/{gba['id']}/contacts", json=contact_body)
    dup = await admin_client.post(
        f"{BASE}/stakeholders/{gba['id']}/contacts", json={**contact_body, "name": "Other", "email": "AMA@ghanabar.org"}
    )
    assert dup.status_code == 409

    contact_id = first.json()["data"]["contacts"][0]["id"]
    missing = await admin_client.put(f"{BASE}/stakeholder-contacts/{contact_id}/consent", json={"consent": "Consented"})
    assert missing.status_code == 422
    missing_withdrawal_evidence = await admin_client.put(
        f"{BASE}/stakeholder-contacts/{contact_id}/consent", json={"consent": "Withdrawn"}
    )
    assert missing_withdrawal_evidence.status_code == 422
    ok = await admin_client.put(
        f"{BASE}/stakeholder-contacts/{contact_id}/consent",
        json={"consent": "Consented", "consentDate": "2026-09-10", "consentChannel": "Form"},
    )
    assert ok.json()["data"]["contacts"][0]["consentDate"] == "2026-09-10"


async def test_segments_resolve_live_and_exclude_unscreened_and_inactive(admin_client: AsyncClient):
    gba = await _create(admin_client, GBA)
    donor = await _create(admin_client, DONOR)
    await admin_client.post(
        f"{BASE}/stakeholders/{gba['id']}/contacts",
        json={
            "name": "Ama",
            "email": "ama@ghanabar.org",
            "consent": "Consented",
            "consentDate": "2026-01-01",
            "consentChannel": "Form",
            "regulated": False,
        },
    )
    await admin_client.post(
        f"{BASE}/stakeholders/{gba['id']}/contacts", json={"name": "Kofi", "email": "kofi@ghanabar.org", "regulated": False}
    )
    await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/contacts", json={"name": "Abena", "email": "abena@lf.org", "regulated": False}
    )

    segment = await admin_client.post(
        f"{BASE}/segments", json={"name": "Everyone", "description": "", "categories": [], "usedBy": ["S075"]}
    )
    data = segment.json()["data"]
    assert (data["members"], data["consented"]) == (2, 1)  # donor contact is unscreened

    consented_only = await admin_client.put(
        f"{BASE}/segments/{data['id']}",
        json={
            "name": "Everyone",
            "categories": [],
            "usedBy": [],
            "criteria": {"categories": [], "statuses": [], "owners": [], "consentedOnly": True},
        },
    )
    assert consented_only.json()["data"]["members"] == 1

    await admin_client.post(f"{BASE}/stakeholders/{gba['id']}/status", json={"status": "Inactive"})
    members = await admin_client.get(f"{BASE}/segments/{data['id']}/members")
    assert members.json()["data"] == []


async def test_import_reports_skipped_rows(admin_client: AsyncClient):
    await _create(admin_client, GBA)
    result = await admin_client.post(
        f"{BASE}/stakeholders/imports",
        json={
            "rows": [GBA, {**GBA, "name": "University of Ghana School of Law", "category": "University", "website": "ug.edu.gh"}]
        },
    )
    data = result.json()["data"]
    assert data["created"] == 1 and data["duplicates"] == 1
    assert data["skipped"][0]["row"] == 1


async def test_auditor_is_read_only(client: AsyncClient):
    await login_as(client, "auditor@clet.gov.gh", "Auditor")
    assert (await client.get(f"{BASE}/stakeholders")).status_code == 200
    denied = await client.post(f"{BASE}/stakeholders", json=GBA)
    assert denied.status_code == 403 and denied.json()["code"] == "PERMISSION_DENIED"
