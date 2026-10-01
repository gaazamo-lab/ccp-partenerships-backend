"""
Seed reference data and (optionally) a demo dataset.

    python -m scripts.seed                 # templates + bootstrap administrator
    python -m scripts.seed --demo          # also demo users and records for UAT

The bootstrap administrator uses BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD.
Demo users share DEMO_PASSWORD (default `Clet-Demo-2026!`) — never run --demo
against production. Every step is idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.core.rbac import Role
from app.core.security import hash_password
from app.models.international import IrLetterTemplate
from app.models.microsites import DEFAULT_TEMPLATES, MicrositeTemplate
from app.models.stakeholders import Stakeholder
from app.models.users import User

DEMO_USERS = [
    ("partnerships@clet.gov.gh", "Nana Asante", Role.PARTNERSHIPS_MANAGER),
    ("officer@clet.gov.gh", "Kofi Mensah", Role.PARTNERSHIPS_OFFICER),
    ("registrar@clet.gov.gh", "Adwoa Sarpong", Role.REGISTRAR),
    ("ir.officer@clet.gov.gh", "Esi Boateng", Role.IR_OFFICER),
    ("letters@clet.gov.gh", "Yaw Darko", Role.CORRESPONDENCE_OFFICER),
    ("ir.head@clet.gov.gh", "Abena Owusu", Role.IR_APPROVER),
    ("content@clet.gov.gh", "Efua Addo", Role.CONTENT_MANAGER),
    ("rmf@clet.gov.gh", "Kwame Ofori", Role.RMF_REVIEWER),
    ("consult@clet.gov.gh", "Akosua Mensah", Role.CONSULTATION_MANAGER),
    ("executive@clet.gov.gh", "Director-General", Role.EXECUTIVE_VIEWER),
    ("auditor@clet.gov.gh", "Internal Audit", Role.AUDITOR),
    # S084 Visa & Travel Authorisation
    ("dti@clet.gov.gh", "Dela Tetteh", Role.DTI_ADMINISTRATOR),
    ("manager@clet.gov.gh", "Efua Kwarteng", Role.LINE_MANAGER),
    ("senior@clet.gov.gh", "Kwabena Asare", Role.SENIOR_APPROVER),
    ("welfare@clet.gov.gh", "Adjoa Nyarko", Role.PC_REVIEWER),
    ("traveller@clet.gov.gh", "Yaw Owusu", Role.TRAVELLER),
]


async def _user(session, email: str, name: str, role: str, password: str) -> None:
    if await session.scalar(select(User).where(func.lower(User.email) == email.lower())) is None:
        session.add(User(email=email, name=name, role=role, password_hash=hash_password(password)))


async def seed_reference(session) -> None:
    for template in DEFAULT_TEMPLATES:
        if await session.get(MicrositeTemplate, template["id"]) is None:
            session.add(MicrositeTemplate(**template))
    letters = [
        (
            "Visit confirmation",
            "EN",
            "Confirmation of your visit to CLET",
            "Dear {{recipient}},\n\nWe are pleased to confirm the visit on {{date}} regarding {{subject}}.\n\nYours faithfully,\n{{sender}}",
        ),
        (
            "Visit confirmation",
            "FR",
            "Confirmation de votre visite au CLET",
            "{{recipient}},\n\nNous avons le plaisir de confirmer la visite du {{date}} concernant {{subject}}.\n\nVeuillez agréer,\n{{sender}}",
        ),
        (
            "Visit confirmation",
            "AR",
            "تأكيد زيارتكم",
            "سعادة {{recipient}}،\n\nيسرنا أن نؤكد الزيارة بتاريخ {{date}} بشأن {{subject}}.\n\nوتفضلوا بقبول فائق الاحترام،\n{{sender}}",
        ),
    ]
    for name, language, subject, body in letters:
        exists = await session.scalar(
            select(IrLetterTemplate).where(IrLetterTemplate.name == name, IrLetterTemplate.language == language)
        )
        if exists is None:
            session.add(IrLetterTemplate(name=name, language=language, subject=subject, body=body, version=1, active=True))


async def seed_demo(session) -> None:
    if await session.scalar(select(func.count()).select_from(Stakeholder)):
        print("Demo records already present; skipping.")
        return
    today = dt.date.today()
    gba = Stakeholder(
        name="Ghana Bar Association",
        short_name="GBA",
        category="Professional body",
        owner="Nana Asante",
        status="Active",
        health="Strong",
        pipeline_stage="Engaged",
        location="Accra",
        website="ghanabar.org",
        description="National professional association of lawyers.",
    )
    ug = Stakeholder(
        name="University of Ghana School of Law",
        short_name="UGSL",
        category="University",
        owner="Kofi Mensah",
        status="Active",
        health="Healthy",
        pipeline_stage="Negotiation",
        location="Legon",
        website="law.ug.edu.gh",
        description="Accredited law faculty.",
    )
    donor = Stakeholder(
        name="Legal Futures Foundation",
        short_name="LFF",
        category="Donor",
        owner="Nana Asante",
        status="Screening pending",
        health="Healthy",
        pipeline_stage="Prospect",
        location="London",
        website="legalfutures.org",
        description="Philanthropic funder of legal education.",
    )
    session.add_all([gba, ug, donor])
    await session.flush()
    # Contacts, engagements, segments, agreements and obligations are seeded by
    # `scripts/demo/crm.py`, which adopts these three organisations by name.


async def run(demo: bool) -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        await seed_reference(session)
        if settings.BOOTSTRAP_ADMIN_PASSWORD:
            await _user(
                session,
                settings.BOOTSTRAP_ADMIN_EMAIL,
                "System Administrator",
                Role.SYSTEM_ADMINISTRATOR,
                settings.BOOTSTRAP_ADMIN_PASSWORD,
            )
        else:
            print("BOOTSTRAP_ADMIN_PASSWORD is not set; no administrator created (use scripts.create_user).")
        if demo:
            if settings.ENV == "production":
                raise SystemExit("Refusing to load demo data in production.")
            password = os.environ.get("DEMO_PASSWORD", "Clet-Demo-2026!")
            await _user(session, "admin.demo@clet.gov.gh", "CRM Administrator", Role.CRM_ADMINISTRATOR, password)
            for email, name, role in DEMO_USERS:
                await _user(session, email, name, role, password)
            await seed_demo(session)
            await session.flush()
            from scripts.demo import seed_all

            await seed_all(session)
        await session.commit()
    await async_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="Load demo users and records (not for production)")
    args = parser.parse_args()
    asyncio.run(run(args.demo))
    print("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
