"""S088: builder validation, approval four-eyes, skip logic, AC-15 identity separation, invitations, themes."""

from __future__ import annotations

import datetime as dt

from httpx import AsyncClient

from app.core.rate_limit import reset_local
from tests.conftest import PASSWORD, make_user

BASE = "/api/v1"


def _body(**overrides) -> dict:
    now = dt.datetime.now(dt.UTC)
    body = {
        "title": "Bar curriculum review",
        "slug": "bar-curriculum-review",
        "summary": "Tell us what the Bar course should teach.",
        "description": "Consultation under §88.",
        "category": "Curriculum",
        "languages": ["English", "French"],
        "opensAt": (now - dt.timedelta(days=1)).isoformat(),
        "closesAt": (now + dt.timedelta(days=30)).isoformat(),
        "estimatedMinutes": 6,
        "anonymousAllowed": True,
        "collectIdentity": False,
        "audienceSource": "PUBLIC",
        "audienceSegmentIds": [],
        "questions": [
            {
                "id": "role",
                "type": "SINGLE_CHOICE",
                "prompt": "Your role",
                "required": True,
                "options": ["Student", "Practitioner"],
                "translations": {"French": {"prompt": "Votre rôle", "options": ["Étudiant", "Praticien"]}},
            },
            {
                "id": "years",
                "type": "NUMBER",
                "prompt": "Years in practice",
                "required": True,
                "min": 0,
                "max": 60,
                "visibleIf": [{"questionId": "role", "operator": "EQUALS", "value": "Practitioner"}],
            },
            {"id": "nps", "type": "NPS", "prompt": "Would you recommend the course?", "required": False},
            {"id": "comments", "type": "LONG_TEXT", "prompt": "Anything else?", "required": False},
        ],
        "triggers": [],
    }
    body.update(overrides)
    return body


async def _switch(http: AsyncClient, email: str, role: str) -> None:
    await http.post(f"{BASE}/auth/logout")
    await make_user(email, role, email.split("@")[0].title())
    assert (await http.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200


async def _open_consultation(http: AsyncClient, **overrides) -> dict:
    created = await http.post(f"{BASE}/consultations", json=_body(**overrides))
    assert created.status_code == 201, created.text
    consultation = created.json()["data"]
    await http.post(f"{BASE}/consultations/{consultation['id']}/status", json={"status": "REVIEW"})
    await _switch(http, "registrar@clet.gov.gh", "Registrar")
    approved = await http.post(f"{BASE}/consultations/{consultation['id']}/status", json={"status": "SCHEDULED"})
    assert approved.status_code == 200, approved.text
    await _switch(http, "manager@clet.gov.gh", "Consultation Manager")
    opened = await http.post(f"{BASE}/consultations/{consultation['id']}/status", json={"status": "OPEN"})
    assert opened.status_code == 200, opened.text
    return opened.json()["data"]


async def test_builder_rejects_forward_skip_logic_and_bad_choices(admin_client: AsyncClient):
    body = _body()
    body["questions"][0]["visibleIf"] = [{"questionId": "years", "operator": "ANSWERED"}]
    assert (await admin_client.post(f"{BASE}/consultations", json=body)).status_code == 422
    body = _body()
    body["questions"][0]["options"] = ["Only one"]
    assert (await admin_client.post(f"{BASE}/consultations", json=body)).status_code == 422


async def test_author_cannot_approve_their_own_consultation(admin_client: AsyncClient):
    created = (await admin_client.post(f"{BASE}/consultations", json=_body())).json()["data"]
    await admin_client.post(f"{BASE}/consultations/{created['id']}/status", json={"status": "REVIEW"})
    denied = await admin_client.post(f"{BASE}/consultations/{created['id']}/status", json={"status": "SCHEDULED"})
    assert denied.status_code == 409 and denied.json()["code"] == "FOUR_EYES"


async def test_public_submission_applies_skip_logic_and_drops_unconsented_identity(admin_client: AsyncClient):
    reset_local()
    consultation = await _open_consultation(admin_client)
    assert consultation["approvedBy"] == "Registrar"
    public = await admin_client.get(f"{BASE}/public/consultations/{consultation['slug']}")
    assert public.json()["data"]["approvedBy"] is None

    missing = await admin_client.post(
        f"{BASE}/public/consultations/{consultation['slug']}/responses",
        json={"language": "English", "answers": {"role": "Practitioner"}, "consentToIdentityLink": False},
    )
    assert missing.status_code == 422 and "years" in missing.json()["fieldErrors"]

    ok = await admin_client.post(
        f"{BASE}/public/consultations/{consultation['slug']}/responses",
        json={
            "language": "French",
            "answers": {"role": "Étudiant", "years": 4, "nps": 9},
            "consentToIdentityLink": False,
            "respondent": {"name": "Kojo", "email": "kojo@example.com", "stakeholderGroup": "Student"},
        },
    )
    assert ok.status_code == 201, ok.text
    responses = (await admin_client.get(f"{BASE}/consultations/{consultation['id']}/responses")).json()["data"]
    assert responses[0]["respondent"] is None  # AC-15: no PII without consent
    assert "years" not in responses[0]["answers"]  # hidden by skip logic, never stored


async def test_closed_consultation_refuses_responses_and_shows_outcome(admin_client: AsyncClient):
    reset_local()
    consultation = await _open_consultation(admin_client)
    await admin_client.post(f"{BASE}/consultations/{consultation['id']}/status", json={"status": "CLOSED"})
    refused = await admin_client.post(
        f"{BASE}/public/consultations/{consultation['slug']}/responses",
        json={"language": "English", "answers": {"role": "Student"}, "consentToIdentityLink": False},
    )
    assert refused.status_code == 409

    await _switch(admin_client, "registrar2@clet.gov.gh", "Registrar")
    await admin_client.put(
        f"{BASE}/consultations/{consultation['id']}/outcome",
        json={"outcomeSummary": "Respondents asked for more practical advocacy training."},
    )
    public = (await admin_client.get(f"{BASE}/public/consultations/{consultation['slug']}")).json()["data"]
    assert public["outcomeSummary"].startswith("Respondents")


async def test_invitations_only_reach_consented_segment_members(admin_client: AsyncClient):
    gba = (await admin_client.post(f"{BASE}/stakeholders", json={"name": "GBA", "category": "Professional body"})).json()["data"]
    await admin_client.post(
        f"{BASE}/stakeholders/{gba['id']}/contacts",
        json={
            "name": "Ama",
            "email": "ama@gba.org",
            "consent": "Consented",
            "consentDate": "2026-01-01",
            "consentChannel": "Form",
        },
    )
    await admin_client.post(f"{BASE}/stakeholders/{gba['id']}/contacts", json={"name": "Kofi", "email": "kofi@gba.org"})
    segment = (await admin_client.post(f"{BASE}/segments", json={"name": "Bar", "categories": ["Professional body"]})).json()[
        "data"
    ]

    consultation = await _open_consultation(
        admin_client, audienceSource="CRM", audienceSegmentIds=[segment["id"]], slug="bar-survey"
    )
    sent = await admin_client.post(
        f"{BASE}/consultations/{consultation['id']}/invitations", json={"kind": "INVITATION", "segmentIds": [segment["id"]]}
    )
    data = sent.json()["data"]
    assert (data["recipientCount"], data["excludedCount"]) == (1, 1)
    assert data["communicationRef"].startswith("S074-OUTBOX-")
    refreshed = (await admin_client.get(f"{BASE}/consultations/{consultation['id']}")).json()["data"]
    assert refreshed["invitedCount"] == 1


async def test_theme_coding(admin_client: AsyncClient):
    reset_local()
    consultation = await _open_consultation(admin_client, slug="theme-test")
    submitted = await admin_client.post(
        f"{BASE}/public/consultations/theme-test/responses",
        json={
            "language": "English",
            "answers": {"role": "Student", "comments": "More moots please"},
            "consentToIdentityLink": False,
        },
    )
    theme = (await admin_client.post(f"{BASE}/consultations/{consultation['id']}/themes", json={"label": "Advocacy"})).json()[
        "data"
    ]
    tagged = await admin_client.put(
        f"{BASE}/consultation-responses/{submitted.json()['data']['id']}/themes",
        json={"questionId": "comments", "themeIds": [theme["id"]]},
    )
    assert tagged.json()["data"]["themes"] == {"comments": [theme["id"]]}
