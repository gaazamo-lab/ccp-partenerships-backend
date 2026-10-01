"""S083: SRS acceptance scenarios T083-01..03 plus approval, readiness and closure gates."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.audit import OutboxEvent
from tests.conftest import PASSWORD, make_user

BASE = "/api/v1/ir"


async def _as(http: AsyncClient, email: str, role: str) -> None:
    await http.post("/api/v1/auth/logout")
    await make_user(email, role, email.split("@")[0].title())
    assert (await http.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200


def _visit(**overrides) -> dict:
    body = {
        "type": "VIP_VISIT",
        "direction": "INBOUND",
        "title": "ECOWAS Court delegation",
        "purpose": "Judicial education cooperation",
        "partnerName": "ECOWAS Court",
        "owner": "Esi Boateng",
        "host": "Director-General",
        "venue": "CLET Boardroom",
        "startAt": "2026-11-10T09:00:00Z",
        "endAt": "2026-11-10T12:00:00Z",
        "timeZone": "Africa/Accra",
        "classification": "INTERNAL",
    }
    body.update(overrides)
    return body


async def _approve(http: AsyncClient, engagement_id: str) -> None:
    await http.post(f"{BASE}/engagements/{engagement_id}/status", json={"status": "SUBMITTED"})
    await _as(http, "head@clet.gov.gh", "IR Approver")
    await http.post(f"{BASE}/engagements/{engagement_id}/status", json={"status": "UNDER_REVIEW"})
    approved = await http.post(f"{BASE}/engagements/{engagement_id}/status", json={"status": "APPROVED", "comment": "Go"})
    assert approved.status_code == 200, approved.text
    await _as(http, "officer2@clet.gov.gh", "IR Officer")


async def test_t083_01_missing_purpose_blocks_submission_and_clash_is_visible(client: AsyncClient):
    await _as(client, "officer@clet.gov.gh", "IR Officer")
    draft = (await client.post(f"{BASE}/engagements", json=_visit(purpose=""))).json()["data"]
    assert draft["reference"].startswith("CLET/IR/")
    blocked = await client.post(f"{BASE}/engagements/{draft['id']}/status", json={"status": "SUBMITTED"})
    assert blocked.status_code == 409 and "purpose" in blocked.json()["message"]

    other = (
        await client.post(
            f"{BASE}/engagements",
            json=_visit(
                title="Embassy courtesy call",
                type="COURTESY_CALL",
                venue="DG Office",
                startAt="2026-11-10T11:00:00Z",
                endAt="2026-11-10T11:30:00Z",
            ),
        )
    ).json()["data"]
    clashes = (await client.get(f"{BASE}/engagements/{other['id']}/clashes")).json()["data"]
    assert [c["id"] for c in clashes] == [draft["id"]]  # same host, overlapping time

    support = await client.post(
        f"{BASE}/engagements/{draft['id']}/support-requests", json={"system": "S084", "description": "Visas for 4 delegates"}
    )
    request = support.json()["data"]["supportRequests"][0]
    assert request["status"] == "REQUESTED"  # submission is not completion
    done_without_ref = await client.patch(
        f"{BASE}/engagements/{draft['id']}/support-requests/{request['id']}", json={"status": "COMPLETED"}
    )
    assert done_without_ref.status_code == 409


async def test_owner_cannot_approve_and_material_change_invalidates_approval(client: AsyncClient):
    await _as(client, "head@clet.gov.gh", "CRM Administrator")
    own = (await client.post(f"{BASE}/engagements", json=_visit())).json()["data"]
    await client.post(f"{BASE}/engagements/{own['id']}/status", json={"status": "SUBMITTED"})
    await client.post(f"{BASE}/engagements/{own['id']}/status", json={"status": "UNDER_REVIEW"})
    denied = await client.post(f"{BASE}/engagements/{own['id']}/status", json={"status": "APPROVED"})
    assert denied.json()["code"] == "FOUR_EYES"

    await _as(client, "officer@clet.gov.gh", "IR Officer")
    visit = (await client.post(f"{BASE}/engagements", json=_visit())).json()["data"]
    await _approve(client, visit["id"])
    moved = await client.put(
        f"{BASE}/engagements/{visit['id']}", json=_visit(startAt="2026-11-11T09:00:00Z", endAt="2026-11-11T12:00:00Z")
    )
    data = moved.json()["data"]
    assert data["status"] == "SUBMITTED" and data["approvals"][-1]["decision"] == "SUBMITTED"


async def test_readiness_and_closure_gates(client: AsyncClient):
    await _as(client, "officer@clet.gov.gh", "IR Officer")
    visit = (await client.post(f"{BASE}/engagements", json=_visit())).json()["data"]
    with_task = await client.post(
        f"{BASE}/engagements/{visit['id']}/protocol-tasks", json={"title": "Seating plan", "mandatory": True, "assignee": "Esi"}
    )
    task = with_task.json()["data"]["protocolTasks"][0]
    await _approve(client, visit["id"])

    not_ready = await client.post(f"{BASE}/engagements/{visit['id']}/status", json={"status": "SCHEDULED"})
    assert not_ready.status_code == 409
    no_evidence = await client.patch(f"{BASE}/engagements/{visit['id']}/protocol-tasks/{task['id']}", json={"status": "DONE"})
    assert no_evidence.status_code == 422
    await client.patch(
        f"{BASE}/engagements/{visit['id']}/protocol-tasks/{task['id']}", json={"status": "DONE", "evidenceRef": "S003-SEAT-1"}
    )
    for status in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
        assert (await client.post(f"{BASE}/engagements/{visit['id']}/status", json={"status": status})).status_code == 200

    follow = await client.post(
        f"{BASE}/engagements/{visit['id']}/follow-ups",
        json={"title": "Send thank-you letter", "owner": "Esi", "dueDate": "2026-11-20", "mandatory": True},
    )
    follow_up = follow.json()["data"]["followUps"][0]
    blocked = await client.post(f"{BASE}/engagements/{visit['id']}/status", json={"status": "CLOSED"})
    assert blocked.status_code == 409 and len(blocked.json()["blockers"]) == 2  # follow-up + minutes

    await client.patch(
        f"{BASE}/engagements/{visit['id']}/follow-ups/{follow_up['id']}",
        json={"status": "EXCEPTION", "exceptionReason": "Sent by DG office"},
    )
    await client.put(f"{BASE}/engagements/{visit['id']}", json=_visit(minutesRef="S003-MIN-7"))
    closed = await client.post(f"{BASE}/engagements/{visit['id']}/status", json={"status": "CLOSED"})
    assert closed.status_code == 200, closed.text


async def test_t083_02_arabic_letter_returned_then_revised_and_only_approved_text_dispatched(client: AsyncClient):
    await _as(client, "writer@clet.gov.gh", "Correspondence Officer")
    template = (
        await client.post(
            f"{BASE}/letter-templates",
            json={"name": "Visit confirmation", "language": "AR", "subject": "تأكيد الزيارة", "body": "سعادة {{recipient}}، ..."},
        )
    ).json()["data"]
    revised = (
        await client.put(
            f"{BASE}/letter-templates/{template['id']}",
            json={
                "name": "Visit confirmation",
                "language": "AR",
                "subject": "تأكيد الزيارة",
                "body": "سعادة {{recipient}}، نؤكد ...",
            },
        )
    ).json()["data"]
    assert revised["version"] == 2

    letter = (
        await client.post(
            f"{BASE}/correspondence",
            json={
                "direction": "OUTBOUND",
                "sender": "Director-General",
                "recipient": "Embassy of Egypt",
                "subject": "تأكيد الزيارة",
                "language": "AR",
                "owner": "Writer",
                "body": "سعادة السفير، نؤكد ...",
                "templateId": revised["id"],
            },
        )
    ).json()["data"]
    assert letter["templateVersion"] == 2 and letter["status"] == "DRAFT"
    await client.post(f"{BASE}/correspondence/{letter['id']}/status", json={"status": "IN_REVIEW"})

    await _as(client, "head@clet.gov.gh", "IR Approver")
    returned = await client.post(
        f"{BASE}/correspondence/{letter['id']}/status", json={"status": "RETURNED", "comment": "Use formal salutation"}
    )
    assert returned.json()["data"]["status"] == "RETURNED"

    await _as(client, "writer2@clet.gov.gh", "Correspondence Officer")
    await client.put(
        f"{BASE}/correspondence/{letter['id']}",
        json={
            **{k: letter[k] for k in ("direction", "sender", "recipient", "subject", "language", "owner")},
            "body": "صاحب السعادة السفير، نؤكد ...",
            "templateId": revised["id"],
        },
    )
    await client.post(f"{BASE}/correspondence/{letter['id']}/status", json={"status": "IN_REVIEW"})
    await _as(client, "head@clet.gov.gh", "IR Approver")
    approved = (await client.post(f"{BASE}/correspondence/{letter['id']}/status", json={"status": "APPROVED"})).json()["data"]
    assert approved["approvedVersion"] == approved["version"] == 2

    await _as(client, "writer3@clet.gov.gh", "Correspondence Officer")
    edit_after = await client.put(
        f"{BASE}/correspondence/{letter['id']}",
        json={
            **{k: letter[k] for k in ("direction", "sender", "recipient", "subject", "language", "owner")},
            "body": "نص غير معتمد",
            "templateId": revised["id"],
        },
    )
    assert edit_after.json()["data"]["status"] == "DRAFT"  # unapproved text cannot be dispatched


async def test_t083_03_received_gift_flags_s011_once_across_retries(client: AsyncClient):
    await _as(client, "officer@clet.gov.gh", "IR Officer")
    unknown_with_value = await client.post(
        f"{BASE}/gifts",
        json={
            "direction": "RECEIVED",
            "giver": "Embassy of Japan",
            "recipient": "Director-General",
            "description": "Vase",
            "giftDate": "2026-09-20",
            "valueKnown": False,
            "value": 10,
        },
    )
    assert unknown_with_value.status_code == 422
    gift = (
        await client.post(
            f"{BASE}/gifts",
            json={
                "direction": "RECEIVED",
                "giver": "Embassy of Japan",
                "recipient": "Director-General",
                "description": "Porcelain vase",
                "giftDate": "2026-09-20",
                "valueKnown": True,
                "value": 1500,
                "currency": "ghs",
            },
        )
    ).json()["data"]
    assert gift["s011Status"] == "PENDING" and gift["currency"] == "GHS"
    retried = (await client.post(f"{BASE}/gifts/{gift['id']}/s011-flag")).json()["data"]
    assert retried["flagAttempts"] == 2

    async with AsyncSessionLocal() as session:
        from sqlalchemy import func, select

        flags = await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.target_system == "S011"))
    assert flags == 1

    given = (
        await client.post(
            f"{BASE}/gifts",
            json={
                "direction": "GIVEN",
                "giver": "CLET",
                "recipient": "Chief Justice of Sierra Leone",
                "description": "Kente stole",
                "giftDate": "2026-09-21",
                "valueKnown": False,
            },
        )
    ).json()["data"]
    assert given["s011Status"] == "NOT_REQUIRED"
