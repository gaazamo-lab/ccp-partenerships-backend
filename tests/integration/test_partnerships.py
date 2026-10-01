"""S082: lifecycle gates, S081 linkage, obligations, renewal, termination, alerts."""

from __future__ import annotations

import datetime as dt

from httpx import AsyncClient

from app.core.config import get_settings

BASE = "/api/v1"


async def _stakeholder(http: AsyncClient, name="Ghana Bar Association", category="Professional body") -> dict:
    response = await http.post(
        f"{BASE}/stakeholders", json={"name": name, "category": category, "owner": "Nana Asante", "website": ""}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _agreement_body(stakeholder_id: str, **overrides) -> dict:
    today = dt.date.today()
    body = {
        "stakeholderId": stakeholder_id,
        "partyStakeholderIds": [stakeholder_id],
        "title": "CLE cooperation",
        "agreementType": "MOU",
        "owner": "Nana Asante",
        "effectiveDate": today.isoformat(),
        "expiryDate": (today + dt.timedelta(days=400)).isoformat(),
        "valueCommitment": "Joint CLE delivery",
        "deliverables": ["Annual CLE programme"],
        "legalContractRef": None,
    }
    body.update(overrides)
    return body


async def _create(http: AsyncClient, body: dict) -> dict:
    response = await http.post(f"{BASE}/partnerships", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _move(http: AsyncClient, agreement_id: str, status: str):
    return await http.post(f"{BASE}/partnerships/{agreement_id}/status", json={"status": status, "note": ""})


async def _activate_ready(http: AsyncClient, agreement: dict) -> None:
    body = {
        k: agreement[k]
        for k in (
            "stakeholderId",
            "partyStakeholderIds",
            "title",
            "agreementType",
            "owner",
            "effectiveDate",
            "expiryDate",
            "valueCommitment",
            "deliverables",
        )
    }
    await http.patch(
        f"{BASE}/partnerships/{agreement['id']}",
        json={**body, "legalContractRef": "S136-CTR-1", "signedDocumentRef": "S003-DOC-1"},
    )
    await http.post(
        f"{BASE}/partnerships/{agreement['id']}/obligations",
        json={"title": "Deliver programme", "owner": "Nana", "dueDate": (dt.date.today() + dt.timedelta(days=60)).isoformat()},
    )


async def test_integration_readiness_is_served_by_backend(admin_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "S203_SCREENING_URL", "https://s203.example/screening-cases")
    response = await admin_client.get(f"{BASE}/partnerships/integrations/health")

    assert response.status_code == 200
    records = response.json()["data"]
    assert {record["system"] for record in records} == {"S003", "S074", "S136", "S203", "S204", "S217", "S225"}
    assert all({"system", "name", "state", "lastCheckedAt", "detail"} <= record.keys() for record in records)
    assert next(record for record in records if record["system"] == "S003")["state"] == "REFERENCE_ONLY"
    assert next(record for record in records if record["system"] == "S203")["state"] == "CONTRACT_READY"


async def test_reference_is_generated_and_duplicates_rejected(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))
    assert agreement["reference"] == f"CLET/MOU/{dt.date.today().year}/001"
    assert agreement["status"] == "DRAFT"

    clash = await admin_client.post(f"{BASE}/partnerships", json=_agreement_body(gba["id"]))
    assert clash.status_code == 409


async def test_parties_must_exist_in_s081(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    response = await admin_client.post(
        f"{BASE}/partnerships",
        json=_agreement_body(gba["id"], partyStakeholderIds=["00000000-0000-0000-0000-000000000001"]),
    )
    assert response.status_code == 422


async def test_lifecycle_gates_and_activation_links_stakeholder(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))

    blocked = await _move(admin_client, agreement["id"], "LEGAL_REVIEW")
    assert blocked.status_code == 409 and blocked.json()["code"] == "TRANSITION_BLOCKED"
    skipped = await _move(admin_client, agreement["id"], "ACTIVE")
    assert skipped.json()["code"] == "INVALID_TRANSITION"

    await _activate_ready(admin_client, agreement)
    assert (await _move(admin_client, agreement["id"], "LEGAL_REVIEW")).status_code == 200
    assert (await _move(admin_client, agreement["id"], "SIGNATURE_PENDING")).status_code == 200
    active = await _move(admin_client, agreement["id"], "ACTIVE")
    assert active.status_code == 200 and active.json()["data"]["status"] == "ACTIVE"

    stakeholder = (await admin_client.get(f"{BASE}/stakeholders/{gba['id']}")).json()["data"]
    assert stakeholder["status"] == "MOU linked"
    assert stakeholder["engagements"][0]["source"] == "S082 MOU Tracker"

    alerts = (await admin_client.get(f"{BASE}/partnerships/{agreement['id']}/renewal-alerts")).json()["data"]
    assert sorted(a["milestoneDays"] for a in alerts) == [30, 90, 180]


async def test_activation_blocked_by_unscreened_party(admin_client: AsyncClient):
    donor = await _stakeholder(admin_client, "Legal Futures Foundation", "Donor")
    await admin_client.post(
        f"{BASE}/stakeholders/{donor['id']}/contacts", json={"name": "Abena", "email": "abena@lff.org", "regulated": True}
    )
    agreement = await _create(admin_client, _agreement_body(donor["id"]))
    await _activate_ready(admin_client, agreement)
    await _move(admin_client, agreement["id"], "LEGAL_REVIEW")
    await _move(admin_client, agreement["id"], "SIGNATURE_PENDING")
    blocked = await _move(admin_client, agreement["id"], "ACTIVE")
    assert blocked.status_code == 409
    assert "screening" in blocked.json()["message"]


async def test_completing_obligation_requires_evidence_and_overdue_is_derived(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    created = await admin_client.post(
        f"{BASE}/partnerships/{agreement['id']}/obligations", json={"title": "Report", "owner": "Nana", "dueDate": past}
    )
    obligation = created.json()["data"]
    assert obligation["status"] == "OVERDUE"

    base = {
        "title": "Report",
        "description": "",
        "owner": "Nana",
        "dueDate": past,
        "reminderLeadDays": None,
        "escalationOwner": None,
    }
    no_evidence = await admin_client.patch(
        f"{BASE}/partnership-obligations/{obligation['id']}", json={**base, "status": "COMPLETED", "evidenceReferences": []}
    )
    assert no_evidence.status_code == 422
    done = await admin_client.patch(
        f"{BASE}/partnership-obligations/{obligation['id']}",
        json={**base, "status": "COMPLETED", "evidenceReferences": ["S003-EV-9"]},
    )
    assert done.json()["data"]["status"] == "COMPLETED"


async def test_termination_needs_closed_obligations_and_cancels_alerts(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))
    await _activate_ready(admin_client, agreement)
    for status in ("LEGAL_REVIEW", "SIGNATURE_PENDING", "ACTIVE"):
        await _move(admin_client, agreement["id"], status)
    termination = {
        "terminatedAt": dt.date.today().isoformat(),
        "reason": "Mutual",
        "documentationRef": "S003-T",
        "finalArchiveRef": "S003-A",
    }
    blocked = await admin_client.post(f"{BASE}/partnerships/{agreement['id']}/termination", json=termination)
    assert blocked.status_code == 409 and blocked.json()["code"] == "TERMINATION_BLOCKED"

    obligation = (await admin_client.get(f"{BASE}/partnerships/{agreement['id']}/obligations")).json()["data"][0]
    await admin_client.post(
        f"{BASE}/partnership-obligations/{obligation['id']}/progress", json={"note": "Waived by board", "status": "WAIVED"}
    )
    done = await admin_client.post(f"{BASE}/partnerships/{agreement['id']}/termination", json=termination)
    assert done.json()["data"]["status"] == "TERMINATED"
    assert done.json()["data"]["termination"]["approvedBy"] == "Ama Admin"
    alerts = (await admin_client.get(f"{BASE}/partnerships/{agreement['id']}/renewal-alerts")).json()["data"]
    assert {a["status"] for a in alerts} == {"CANCELLED"}


async def test_renewal_records_history_and_reschedules_alerts(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))
    await _activate_ready(admin_client, agreement)
    for status in ("LEGAL_REVIEW", "SIGNATURE_PENDING", "ACTIVE"):
        await _move(admin_client, agreement["id"], status)
    new_expiry = (dt.date.today() + dt.timedelta(days=1200)).isoformat()
    renewed = await admin_client.post(
        f"{BASE}/partnerships/{agreement['id']}/renewals",
        json={
            "effectiveDate": agreement["expiryDate"],
            "expiryDate": new_expiry,
            "legalContractRef": "S136-2",
            "signedDocumentRef": "S003-2",
            "termsSummary": "Three more years",
        },
    )
    assert renewed.json()["data"]["renewalCount"] == 1
    renewals = (await admin_client.get(f"{BASE}/partnerships/{agreement['id']}/renewals")).json()["data"]
    assert renewals[0]["previousSignedDocumentRef"] == "S003-DOC-1"
    alerts = (await admin_client.get(f"{BASE}/partnerships/{agreement['id']}/renewal-alerts")).json()["data"]
    assert len([a for a in alerts if a["status"] != "CANCELLED"]) == 3


async def test_due_alert_dispatches_through_outbox_and_can_be_acknowledged(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    soon = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    agreement = await _create(admin_client, _agreement_body(gba["id"], expiryDate=soon))
    configured = await admin_client.put(
        f"{BASE}/partnerships/{agreement['id']}/renewal-alerts", json={"recipients": ["partnerships@clet.gov.gh"]}
    )
    alerts = configured.json()["data"]
    due = next(a for a in alerts if a["status"] == "DUE")
    scheduled = next(a for a in alerts if a["status"] == "SCHEDULED")

    assert (await admin_client.post(f"{BASE}/partnership-renewal-alerts/{scheduled['id']}/dispatch")).status_code == 409
    sent = await admin_client.post(f"{BASE}/partnership-renewal-alerts/{due['id']}/dispatch")
    assert sent.json()["data"]["status"] == "SENT"
    assert sent.json()["data"]["communicationRef"].startswith("S074-OUTBOX-")
    acked = await admin_client.post(f"{BASE}/partnership-renewal-alerts/{due['id']}/acknowledgement")
    assert acked.json()["data"]["acknowledgedBy"] == "Ama Admin"


async def test_stale_if_match_is_rejected(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    agreement = await _create(admin_client, _agreement_body(gba["id"]))
    body = {**_agreement_body(gba["id"]), "signedDocumentRef": None}
    stale = await admin_client.patch(f"{BASE}/partnerships/{agreement['id']}", json=body, headers={"If-Match": '"99"'})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_WRITE"
    fresh = await admin_client.patch(f"{BASE}/partnerships/{agreement['id']}", json=body, headers={"If-Match": '"1"'})
    assert fresh.status_code == 200 and fresh.headers["etag"] == '"2"'
