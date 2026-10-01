"""Background jobs: outbox relay (S011 acknowledgement), partnership and consultation sweeps."""

from __future__ import annotations

import datetime as dt
import json

import httpx
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.database import SyncSessionFactory
from app.models.audit import OutboxEvent
from app.models.international import IrGift
from app.models.partnerships import PartnershipAgreement
from app.tasks.jobs import consultation_sweep, partnership_sweep, relay_outbox
from tests.integration.test_consultations import _open_consultation
from tests.integration.test_partnerships import _agreement_body, _create, _stakeholder
from tests.integration.test_stakeholders import DONOR
from tests.integration.test_stakeholders import _create as _create_stakeholder


async def test_relay_delivers_s203_screening_request_with_service_key(admin_client: AsyncClient, monkeypatch):
    donor = await _create_stakeholder(admin_client, DONOR)
    created = await admin_client.post(
        f"/api/v1/stakeholders/{donor['id']}/contacts",
        json={
            "name": "Abena Mensah",
            "role": "Director",
            "email": "abena@legalfutures.org",
            "consent": "Not recorded",
            "regulated": False,
        },
    )
    contact_id = created.json()["data"]["contacts"][0]["id"]
    monkeypatch.setattr(get_settings(), "S203_SCREENING_URL", "https://s203.example/api/screening-cases")
    monkeypatch.setattr(get_settings(), "S203_API_KEY", "s203-secret")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"key": request.headers["X-Api-Key"], "body": json.loads(request.content)})
        return httpx.Response(202, json={"reference": "S203-QUEUE-77"})

    with SyncSessionFactory() as session:
        result = relay_outbox(session, httpx.Client(transport=httpx.MockTransport(handler)))
        row = session.query(OutboxEvent).filter_by(target_system="S203").one()
        assert result["sent"] == 1 and row.status == "SENT" and row.external_ref == "S203-QUEUE-77"
    assert seen[0]["key"] == "s203-secret"
    assert seen[0]["body"]["payload"]["caseId"] == contact_id


async def test_relay_delivers_s011_flag_and_marks_gift_acknowledged(admin_client: AsyncClient, monkeypatch):
    gift = (
        await admin_client.post(
            "/api/v1/ir/gifts",
            json={
                "direction": "RECEIVED",
                "giver": "Embassy",
                "recipient": "DG",
                "description": "Book",
                "giftDate": "2026-09-01",
                "valueKnown": False,
            },
        )
    ).json()["data"]

    with SyncSessionFactory() as session:
        skipped = relay_outbox(session, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert skipped["sent"] == 0  # no S011 URL configured: held in the outbox

    monkeypatch.setattr(get_settings(), "S011_GIFTS_URL", "https://s011.example/flags")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Idempotency-Key"])
        return httpx.Response(200, json={"reference": "S011-FLAG-77"})

    with SyncSessionFactory() as session:
        result = relay_outbox(session, httpx.Client(transport=httpx.MockTransport(handler)))
        stored = session.get(IrGift, __import__("uuid").UUID(gift["id"]))
        assert result["sent"] == 1
        assert stored.s011_status == "ACKNOWLEDGED" and stored.s011_ref == "S011-FLAG-77"
    assert seen == [f"s011-gift:{gift['id']}"]


async def test_failed_delivery_backs_off(admin_client: AsyncClient, monkeypatch):
    await admin_client.post(
        "/api/v1/ir/gifts",
        json={
            "direction": "RECEIVED",
            "giver": "Embassy",
            "recipient": "DG",
            "description": "Book",
            "giftDate": "2026-09-01",
            "valueKnown": False,
        },
    )
    monkeypatch.setattr(get_settings(), "S011_GIFTS_URL", "https://s011.example/flags")
    with SyncSessionFactory() as session:
        result = relay_outbox(session, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
        row = session.query(OutboxEvent).filter_by(target_system="S011").one()
        assert result["failed"] == 1 and row.attempts == 1 and row.status == "PENDING"
        assert row.next_attempt_at is not None


async def test_partnership_sweep_moves_to_renewal_due_and_expired(admin_client: AsyncClient):
    gba = await _stakeholder(admin_client)
    soon = await _create(
        admin_client, _agreement_body(gba["id"], title="Soon", expiryDate=(dt.date.today() + dt.timedelta(days=40)).isoformat())
    )
    with SyncSessionFactory() as session:
        row = session.get(PartnershipAgreement, __import__("uuid").UUID(soon["id"]))
        row.status = "ACTIVE"
        session.commit()
        assert partnership_sweep(session)["renewal_due"] == 1
        assert partnership_sweep(session, today=dt.date.today() + dt.timedelta(days=41))["expired"] == 1


async def test_consultation_sweep_closes_past_window(admin_client: AsyncClient):
    from app.core.rate_limit import reset_local

    reset_local()
    consultation = await _open_consultation(admin_client, slug="sweep-test")
    with SyncSessionFactory() as session:
        from app.models.consultations import Consultation

        row = session.get(Consultation, __import__("uuid").UUID(consultation["id"]))
        row.closes_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        session.commit()
        assert consultation_sweep(session)["closed"] == 1
