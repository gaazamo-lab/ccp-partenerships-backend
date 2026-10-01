"""S084: evidence gate, approval chain, issuance gate, amendment reset, record scope."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import login_as

BASE = "/api/v1"

OUTBOUND = {
    "direction": "Outbound",
    "category": "Official travel",
    "traveller": "Ama Serwaa Boateng",
    "purpose": "Bilateral legal education mission",
    "destination": "Nairobi, Kenya",
    "startDate": "2026-11-02",
    "endDate": "2026-11-07",
}


async def _request(http: AsyncClient, **overrides) -> dict:
    response = await http.post(f"{BASE}/travel-requests", json={**OUTBOUND, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _clear_evidence(http: AsyncClient, request: dict) -> dict:
    for index in range(len(request["evidence"])):
        response = await http.put(
            f"{BASE}/travel-requests/{request['id']}/evidence/{index}",
            json={"status": "Received", "detail": f"S003-DOC-2026-000{index}"},
        )
        assert response.status_code == 200, response.text
        request = response.json()["data"]
    return request


async def _to_pending_approvals(http: AsyncClient, request: dict) -> dict:
    request = await _clear_evidence(http, request)
    for _ in range(3):  # Submitted, Screening, Pending approvals
        response = await http.post(f"{BASE}/travel-requests/{request['id']}/advance")
        assert response.status_code == 200, response.text
        request = response.json()["data"]
    assert request["status"] == "Pending approvals"
    return request


async def test_reference_is_allocated_and_checklist_matches_the_category(admin_client: AsyncClient):
    first = await _request(admin_client)
    assert first["reference"].startswith("S084-")
    assert first["status"] == "Draft"
    assert {item["status"] for item in first["evidence"]} == {"Missing"}

    second = await _request(admin_client, traveller="Kwame Adjei")
    assert second["reference"] != first["reference"]

    student = await _request(
        admin_client, category="Student outbound travel", traveller="Akos Mensah", studentNumber="CLET/2024/118"
    )
    labels = [item["label"] for item in student["evidence"]]
    assert "Parent or guardian consent" in labels
    # The welfare check only exists on the student chain.
    assert any(step["assignee"] == "P&C Reviewer" for step in student["approvals"])
    assert not any(step["assignee"] == "P&C Reviewer" for step in first["approvals"])


async def test_inbound_requires_nationality(admin_client: AsyncClient):
    response = await admin_client.post(f"{BASE}/travel-requests", json={**OUTBOUND, "direction": "Inbound", "nationality": ""})
    assert response.status_code == 422
    ok = await _request(admin_client, direction="Inbound", nationality="Kenyan")
    # Inbound adds the IR protocol clearance step and the S083 handoff.
    assert any(step["label"] == "IR protocol clearance" for step in ok["approvals"])
    assert any(row["system"] == "S083" for row in ok["integrations"])


async def test_evidence_gate_blocks_submission(admin_client: AsyncClient):
    request = await _request(admin_client)
    blocked = await admin_client.post(f"{BASE}/travel-requests/{request['id']}/advance")
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "TRAVEL_EVIDENCE_INCOMPLETE"

    # An exception clears the gate, but only with a recorded reason.
    no_reason = await admin_client.put(f"{BASE}/travel-requests/{request['id']}/evidence/0", json={"status": "Exception"})
    assert no_reason.status_code == 422

    waived = await admin_client.put(
        f"{BASE}/travel-requests/{request['id']}/evidence/0",
        json={"status": "Exception", "detail": "Held by the mission until the interview."},
    )
    assert waived.status_code == 200
    assert waived.json()["data"]["evidence"][0]["exceptionReason"]

    request = await _clear_evidence(admin_client, waived.json()["data"])
    moved = await admin_client.post(f"{BASE}/travel-requests/{request['id']}/advance")
    assert moved.status_code == 200
    assert moved.json()["data"]["status"] == "Submitted"


async def test_approval_chain_and_issuance_gate(admin_client: AsyncClient):
    request = await _to_pending_approvals(admin_client, await _request(admin_client))

    early = await admin_client.post(
        f"{BASE}/travel-requests/{request['id']}/documents",
        json={"signatory": "Registrar", "templateVersion": "S084 standard v3.1"},
    )
    assert early.status_code == 409
    assert early.json()["code"] == "TRAVEL_NOT_APPROVED"

    for step in request["approvals"]:
        response = await admin_client.post(
            f"{BASE}/travel-requests/{request['id']}/approvals/{step['id']}",
            json={"decision": "Approved", "comment": "Cleared."},
        )
        assert response.status_code == 200, response.text
        request = response.json()["data"]
    assert request["status"] == "Approved"

    # The same step cannot be decided twice.
    again = await admin_client.post(
        f"{BASE}/travel-requests/{request['id']}/approvals/{request['approvals'][0]['id']}",
        json={"decision": "Approved", "comment": "Again."},
    )
    assert again.status_code == 409

    issued = await admin_client.post(
        f"{BASE}/travel-requests/{request['id']}/documents",
        json={"signatory": "Registrar", "templateVersion": "S084 standard v3.1"},
    )
    assert issued.status_code == 200
    request = issued.json()["data"]
    assert request["status"] == "Travel authorised"
    assert request["issuedDocuments"][-1]["status"] == "Current"

    completed = (await admin_client.post(f"{BASE}/travel-requests/{request['id']}/advance")).json()["data"]
    assert completed["status"] == "Completed"
    closed = await admin_client.post(f"{BASE}/travel-requests/{request['id']}/closure", json={"outcome": "Completed as planned."})
    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "Closed"
    # A closed request accepts no further movement.
    assert (await admin_client.post(f"{BASE}/travel-requests/{request['id']}/advance")).status_code == 409


async def test_rejection_supersedes_the_outstanding_steps(admin_client: AsyncClient):
    request = await _to_pending_approvals(admin_client, await _request(admin_client))
    response = await admin_client.post(
        f"{BASE}/travel-requests/{request['id']}/approvals/{request['approvals'][0]['id']}",
        json={"decision": "Rejected", "comment": "Not funded this quarter."},
    )
    assert response.status_code == 200
    request = response.json()["data"]
    assert request["status"] == "Rejected"
    assert request["approvals"][1]["status"] == "Superseded"


async def test_amendment_resets_approvals_and_supersedes_the_document(admin_client: AsyncClient):
    request = await _to_pending_approvals(admin_client, await _request(admin_client))
    for step in request["approvals"]:
        request = (
            await admin_client.post(
                f"{BASE}/travel-requests/{request['id']}/approvals/{step['id']}",
                json={"decision": "Approved", "comment": "Cleared."},
            )
        ).json()["data"]
    request = (
        await admin_client.post(
            f"{BASE}/travel-requests/{request['id']}/documents",
            json={"signatory": "Registrar", "templateVersion": "S084 standard v3.1"},
        )
    ).json()["data"]

    amended = await admin_client.post(
        f"{BASE}/travel-requests/{request['id']}/amendments",
        json={
            "destination": "Kigali, Rwanda",
            "startDate": "2026-11-09",
            "endDate": "2026-11-14",
            "reason": "Host moved the summit.",
        },
    )
    assert amended.status_code == 200
    request = amended.json()["data"]
    assert request["destination"] == "Kigali, Rwanda"
    # An approval given against the old itinerary must not carry over.
    assert request["status"] == "Pending approvals"
    assert {step["status"] for step in request["approvals"]} == {"Pending"}
    assert request["issuedDocuments"][-1]["status"] == "Superseded"


async def test_estimate_derives_per_diem_and_names_the_rate_version(admin_client: AsyncClient):
    request = await _request(admin_client)
    response = await admin_client.put(
        f"{BASE}/travel-requests/{request['id']}/estimate",
        json={
            "currency": "GHS",
            "eligibleDays": 5,
            "dailyRate": 1800,
            "transport": 9500,
            "accommodation": 4200,
            "other": 0,
            "rateVersion": "RATE-2026.1",
        },
    )
    assert response.status_code == 200
    estimate = response.json()["data"]["estimate"]
    assert estimate["perDiem"] == 9000
    assert estimate["rateVersion"] == "RATE-2026.1"


async def test_traveller_sees_only_their_own_requests(client: AsyncClient):
    await login_as(client, "dti@clet.gov.gh", "DTI Administrator", "Dela Tetteh")
    mine = await _request(client, traveller="Yaw Owusu")
    await _request(client, traveller="Someone Else")

    await login_as(client, "yaw@clet.gov.gh", "Traveller", "Yaw Owusu")
    listing = await client.get(f"{BASE}/travel-requests")
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert [row["id"] for row in rows] == [mine["id"]]

    # Another traveller's request reads as absent, not as forbidden.
    other = await client.get(f"{BASE}/travel-requests/{rows[0]['id']}")
    assert other.status_code == 200
    await login_as(client, "kofi@clet.gov.gh", "Traveller", "Kofi Mensah")
    assert (await client.get(f"{BASE}/travel-requests/{mine['id']}")).status_code == 404


async def test_approver_cannot_configure_policy(client: AsyncClient):
    await login_as(client, "manager@clet.gov.gh", "Line Manager", "Efua Kwarteng")
    assert (await client.get(f"{BASE}/travel-policy")).status_code == 200
    denied = await client.put(
        f"{BASE}/travel-policy",
        json={
            "policyVersion": "TRV-5.0",
            "rateVersion": "RATE-2027.1",
            "currency": "GHS",
            "dailyRates": {"Regional": 1500},
            "supportTemplate": "S084 standard v3.1",
            "authorisationTemplate": "S084 standard v3.1",
            "escalationDays": 5,
        },
    )
    assert denied.status_code == 403

    await login_as(client, "dti2@clet.gov.gh", "DTI Administrator", "Dela Tetteh")
    allowed = await client.put(
        f"{BASE}/travel-policy",
        json={
            "policyVersion": "TRV-5.0",
            "rateVersion": "RATE-2027.1",
            "currency": "GHS",
            "dailyRates": {"Regional": 1500},
            "supportTemplate": "S084 standard v3.1",
            "authorisationTemplate": "S084 standard v3.1",
            "escalationDays": 5,
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["rateVersion"] == "RATE-2027.1"


async def test_module_registry_reports_every_bounded_context(admin_client: AsyncClient):
    """A portal going down must be visible without reading logs."""
    response = await admin_client.get(f"{BASE}/modules")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["loaded"] == body["meta"]["total"]
    travel = next(row for row in body["data"] if row["module"] == "travel")
    assert travel["system"] == "S084"
    assert travel["portals"] == ["travel-authorisation"]
