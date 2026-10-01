# ruff: noqa: E501
"""S083 International Relations & Protocols demo dataset.

Ported from ``partner-crm/apps/ir-workspace/src/features/international/data/seed.ts`` and dated
relative to today so upcoming visits stay upcoming and overdue letters stay overdue. Idempotent
(marker: the first engagement's title) and does not commit.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, func, select

from app.models.international import IrCorrespondence, IrEngagement, IrGift, IrLetterTemplate
from app.models.stakeholders import Stakeholder
from app.models.users import User

MARKER_TITLE = "ECOWAS Commission delegation on regional legal education"
LEGACY_TITLE = "ECOWAS Court delegation"  # the minimal record the old seed_demo created

_MIDNIGHT = dt.datetime.combine(dt.date.today(), dt.time(0, 0), tzinfo=dt.UTC)
_YEAR = dt.date.today().year

_MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
_MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def at(days: int, hour: int = 9, minute: int = 0) -> dt.datetime:
    return _MIDNIGHT + dt.timedelta(days=days, hours=hour, minutes=minute)


def iso(days: int, hour: int = 9) -> str:
    return at(days, hour).isoformat()


def day(days: int) -> dt.date:
    return at(days).date()


def day_iso(days: int) -> str:
    return day(days).isoformat()


def _en(days: int) -> str:
    d = day(days)
    return f"{d.day} {_MONTHS_EN[d.month - 1]} {d.year}"


def _fr(days: int) -> str:
    d = day(days)
    return f"{d.day} {_MONTHS_FR[d.month - 1]} {d.year}"


def _ar(days: int) -> str:
    d = day(days)
    digits = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
    return f"{d.day} {_MONTHS_AR[d.month - 1]} {d.year}".translate(digits)


def ir_ref(seq: int) -> str:
    return f"CLET/IR/{_YEAR}/{seq:03d}"


def cor_ref(seq: int) -> str:
    return f"CLET/COR/{_YEAR}/{seq:03d}"


# ── item builders (ids are stable strings, as the API mints them) ──


def member(key: str, name: str, role: str, org: str, nationality: str, contact=None, travel=None) -> dict[str, Any]:
    return {
        "id": f"del-{key}",
        "name": name,
        "contactRef": contact,
        "role": role,
        "organisation": org,
        "nationality": nationality,
        "travelRequestRef": travel,
    }


def task(key: str, title: str, assignee: str, due: int | None, status: str, mandatory=True, evidence=None, reason=None):
    return {
        "id": f"tsk-{key}",
        "title": title,
        "mandatory": mandatory,
        "assignee": assignee,
        "dueDate": day_iso(due) if due is not None else None,
        "status": status,
        "evidenceRef": evidence,
        "exceptionReason": reason,
    }


def follow_up(key: str, title: str, owner: str, due: int, status: str, mandatory=True, reason=None):
    return {
        "id": f"fup-{key}",
        "title": title,
        "owner": owner,
        "dueDate": day_iso(due),
        "mandatory": mandatory,
        "status": status,
        "exceptionReason": reason,
    }


def support(key: str, system: str, description: str, status: str, requested: int, updated: int, external=None, hour=10):
    return {
        "id": f"sup-{key}",
        "system": system,
        "description": description,
        "externalRef": external,
        "status": status,
        "requestedAt": iso(requested, hour),
        "updatedAt": iso(updated, hour + 4),
    }


def approval(key: str, decision: str, comment: str, actor: str, version: int, when: int, hour=11):
    return {
        "id": f"apr-{key}",
        "decision": decision,
        "comment": comment,
        "actor": actor,
        "version": version,
        "occurredAt": iso(when, hour),
    }


async def _user_ids(session) -> dict[str, tuple[str, str]]:
    rows = (await session.execute(select(User.email, User.id, User.name))).all()
    return {email.lower(): (str(uid), name) for email, uid, name in rows}


async def _stakeholder(session, *needles: str):
    for needle in needles:
        found = await session.scalar(
            select(Stakeholder.id).where(func.lower(Stakeholder.name).like(f"%{needle.lower()}%")).limit(1)
        )
        if found is not None:
            return found
    return None


async def _seed_templates(session) -> dict[str, IrLetterTemplate]:
    """Visit confirmation EN v1 (superseded) / v2 (active), FR v1, AR v1; replaces the bare reference ones."""
    name = "Visit confirmation"
    rows = {
        (t.language, t.version): t
        for t in (await session.scalars(select(IrLetterTemplate).where(IrLetterTemplate.name == name))).all()
    }

    def get(language: str, version: int) -> IrLetterTemplate:
        row = rows.get((language, version)) or IrLetterTemplate(name=name, language=language, version=version, subject="", body="")
        session.add(row)
        return row

    en_v1 = get("EN", 1)
    en_v1.subject = "Confirmation of {{engagement}}"
    en_v1.body = "Dear {{recipient}},\n\nWe confirm the arrangements for {{engagement}}.\n\nYours faithfully,\n{{sender}}\n{{date}}"
    en_v1.active = False
    en_v1.updated_at = at(-120, 10)

    en_v2 = get("EN", 2)
    en_v2.subject = "Confirmation of arrangements: {{subject}}"
    en_v2.body = (
        "Your Excellency {{recipient}},\n\nThe {{sender}} presents its compliments and has the honour to confirm the "
        "arrangements for {{engagement}}, concerning {{subject}}.\n\nThe detailed programme and protocol arrangements "
        "are enclosed. Our International Relations & Protocols Unit remains at your disposal for any further "
        "information.\n\nThe {{sender}} avails itself of this opportunity to renew the assurances of its highest "
        "consideration.\n\nAccra, {{date}}"
    )
    en_v2.active = True
    en_v2.updated_at = at(-60, 10)

    fr = get("FR", 1)
    fr.subject = "Confirmation des dispositions : {{subject}}"
    fr.body = (
        "Excellence {{recipient}},\n\nLe {{sender}} présente ses compliments et a l’honneur de confirmer les dispositions "
        "relatives à {{engagement}}, concernant {{subject}}.\n\nLe programme détaillé et les dispositions protocolaires "
        "sont joints à la présente. Notre Unité des Relations Internationales et du Protocole reste à votre disposition "
        "pour toute information complémentaire.\n\nLe {{sender}} saisit cette occasion pour vous renouveler l’assurance "
        "de sa très haute considération.\n\nFait à Accra, le {{date}}"
    )
    fr.active = True
    fr.updated_at = at(-60, 11)

    ar = get("AR", 1)
    ar.subject = "تأكيد الترتيبات: {{subject}}"
    ar.body = (
        "سعادة {{recipient}}،\n\nيهدي {{sender}} أطيب تحياته، ويتشرف بأن يؤكد الترتيبات الخاصة بـ {{engagement}} بشأن "
        "{{subject}}.\n\nمرفق طيه البرنامج التفصيلي والترتيبات البروتوكولية. وتظل وحدة العلاقات الدولية والمراسم لدينا "
        "رهن إشارتكم لأي معلومات إضافية.\n\nويغتنم {{sender}} هذه الفرصة ليعرب لكم عن فائق التقدير والاحترام.\n\n"
        "أكرا، في {{date}}"
    )
    ar.active = True
    ar.updated_at = at(-60, 12)

    # Two more active templates so the library is not a single family.
    extras = [
        (
            "Thank-you letter",
            "EN",
            "Thank you for {{engagement}}",
            "Dear {{recipient}},\n\nOn behalf of the {{sender}}, thank you for {{engagement}}. We look forward to "
            "continuing our cooperation on {{subject}}.\n\nYours sincerely,\n{{sender}}\n{{date}}",
        ),
        (
            "Note verbale",
            "FR",
            "Note verbale : {{subject}}",
            "Le {{sender}} présente ses compliments à {{recipient}} et a l’honneur de se référer à {{subject}}.\n\n"
            "Le {{sender}} saisit cette occasion pour renouveler à {{recipient}} l’assurance de sa haute considération.\n\n"
            "Accra, le {{date}}",
        ),
    ]
    for n, lang, subject, body in extras:
        exists = await session.scalar(
            select(IrLetterTemplate).where(IrLetterTemplate.name == n, IrLetterTemplate.language == lang)
        )
        if exists is None:
            session.add(
                IrLetterTemplate(name=n, language=lang, version=1, subject=subject, body=body, active=True, updated_at=at(-30, 10))
            )
    await session.flush()
    return {"en2": en_v2, "fr1": fr, "ar1": ar}


async def seed(session) -> None:
    if await session.scalar(select(IrEngagement.id).where(IrEngagement.title == MARKER_TITLE)):
        return

    # Replace the minimal engagement the old core seed created (would collide on CLET/IR/<year>/001).
    await session.execute(delete(IrEngagement).where(IrEngagement.title == LEGACY_TITLE))
    await session.flush()

    users = await _user_ids(session)
    officer_id, _ = users.get("ir.officer@clet.gov.gh", ("seed-ir-officer", "Esi Boateng"))
    letters_id, letters_name = users.get("letters@clet.gov.gh", ("seed-letters", "Yaw Darko"))
    head_id, head_name = users.get("ir.head@clet.gov.gh", ("seed-ir-head", "Abena Owusu"))

    templates = await _seed_templates(session)

    ecowas = await _stakeholder(session, "ecowas commission", "ecowas")
    morocco = await _stakeholder(session, "morocco")
    clea = await _stakeholder(session, "commonwealth legal education", "commonwealth")
    nigeria = await _stakeholder(session, "council of legal education", "nigeria")
    kenya = await _stakeholder(session, "kenya school of law", "kenya")
    japan = await _stakeholder(session, "japan", "jica")
    uk = await _stakeholder(session, "british high commission", "united kingdom")

    def eng(seq: int, **kw) -> IrEngagement:
        created = kw.pop("created")
        updated = kw.pop("updated")
        return IrEngagement(
            reference=ir_ref(seq),
            owner_id=officer_id,
            time_zone=kw.pop("time_zone", "Africa/Accra"),
            classification=kw.pop("classification", "INTERNAL"),
            checklist_version=kw.pop("checklist_version", 1),
            version=kw.pop("version", 1),
            delegation=kw.pop("delegation", []),
            protocol_tasks=kw.pop("protocol_tasks", []),
            follow_ups=kw.pop("follow_ups", []),
            support_requests=kw.pop("support_requests", []),
            approvals=kw.pop("approvals", []),
            created_at=created,
            updated_at=updated,
            **kw,
        )

    e1 = eng(
        1,
        type="VIP_VISIT",
        direction="INBOUND",
        title=MARKER_TITLE,
        purpose="Working visit by the ECOWAS Commissioner for Human Development to review harmonisation of professional legal training across member states and sign a joint statement of intent.",
        partner_stakeholder_id=ecowas,
        partner_name="ECOWAS Commission",
        owner="Akosua Mensah",
        host="Director-General, CLET",
        venue="CLET Head Office, Accra — Council Chamber",
        start_at=at(9, 9),
        end_at=at(10, 16),
        classification="CONFIDENTIAL",
        status="APPROVED",
        checklist_version=3,
        agenda_ref="S003-DOC-2026-11820",
        briefing_pack_ref="S003-DOC-2026-11834",
        version=2,
        delegation=[
            member("001", "Prof. Fatou Sarr Sow", "Head of delegation — Commissioner", "ECOWAS Commission", "Senegalese", "con-041", "S084-TR-2026-0412"),
            member("002", "Dr. Emeka Okonkwo", "Director, Education, Science & Culture", "ECOWAS Commission", "Nigerian", "con-042", "S084-TR-2026-0413"),
            member("003", "Mariama Diallo", "Protocol officer", "ECOWAS Commission", "Guinean", None, "S084-TR-2026-0414"),
            member("004", "João Tavares", "Interpreter (PT/FR/EN)", "ECOWAS Commission", "Cabo Verdean"),
        ],
        protocol_tasks=[
            task("001", "Security clearance with Ghana Police VIP Protection Unit", "Kwabena Owusu", 2, "DONE", evidence="S003-DOC-2026-11851"),
            task("002", "Airport reception and VIP lounge booking at KIA", "Kwabena Owusu", 6, "OPEN"),
            task("003", "Confirm simultaneous interpretation (FR/PT)", "Efua Asante", 5, "OPEN"),
            task("004", "Order of precedence and seating plan", "Akosua Mensah", 7, "DONE", evidence="S003-DOC-2026-11866"),
            task("005", "Select official gift (kente stole with CLET crest)", "Efua Asante", 8, "OPEN", mandatory=False),
        ],
        support_requests=[
            support("001", "S084", "Visa invitation letters and hotel block for four delegates", "ACKNOWLEDGED", -14, -12, "S084-TR-2026-0412"),
            support("002", "S078", "Signing ceremony and working lunch in the Council Chamber", "REQUESTED", -6, -6, hour=11),
            support("003", "S086", "French translation of the joint statement of intent", "FAILED", -5, -4, hour=9),
        ],
        approvals=[
            approval("001", "SUBMITTED", "Visit plan, delegation and briefing pack ready for approval.", "Akosua Mensah", 2, -10),
            approval("002", "APPROVED", "Approved. Confirm interpretation before scheduling.", head_name, 2, -8, 14),
        ],
        created=at(-21, 9),
        updated=at(-8, 14),
    )
    e2 = eng(
        2,
        type="COURTESY_CALL",
        direction="INBOUND",
        title="Courtesy call — Ambassador of the Kingdom of Morocco",
        purpose="Introductory courtesy call by the new Ambassador to discuss judicial-training exchanges with the Institut Supérieur de la Magistrature.",
        partner_stakeholder_id=morocco,
        partner_name="Embassy of the Kingdom of Morocco",
        owner="Yaw Darko",
        host="Director-General, CLET",
        venue="Director-General's Office, CLET Head Office",
        start_at=at(9, 14),
        end_at=at(9, 15),
        status="UNDER_REVIEW",
        briefing_pack_ref="S003-DOC-2026-11902",
        delegation=[
            member("010", "H.E. Imane Ouaadil", "Ambassador", "Embassy of the Kingdom of Morocco", "Moroccan", "con-057"),
            member("011", "Karim Benjelloun", "First Counsellor", "Embassy of the Kingdom of Morocco", "Moroccan"),
        ],
        protocol_tasks=[task("010", "Prepare French-language briefing note", "Efua Asante", 7, "OPEN")],
        approvals=[approval("010", "SUBMITTED", "Requested by the Embassy note verbale of last week.", "Yaw Darko", 1, -2, 10)],
        created=at(-4, 9),
        updated=at(-2, 10),
    )
    e3 = eng(
        3,
        type="CONFERENCE",
        direction="OUTBOUND",
        title="CLEA Pan-African Legal Education Conference, Nairobi",
        purpose="Present the Ghana School of Law reform programme and lead the panel on practical legal training standards.",
        partner_stakeholder_id=clea,
        partner_name="Commonwealth Legal Education Association",
        owner="Nana Yaw Boateng",
        host="Commonwealth Legal Education Association",
        venue="Kenyatta International Convention Centre, Nairobi",
        start_at=at(20, 8),
        end_at=at(22, 17),
        time_zone="Africa/Nairobi",
        classification="PUBLIC",
        status="SCHEDULED",
        checklist_version=2,
        agenda_ref="S003-DOC-2026-11710",
        briefing_pack_ref="S003-DOC-2026-11745",
        delegation=[
            member("020", "Justice (Rtd) Abena Frimpong", "Head of delegation — Director-General", "CLET", "Ghanaian", None, "S084-TR-2026-0388"),
            member("021", "Nana Yaw Boateng", "Panel lead", "CLET", "Ghanaian", None, "S084-TR-2026-0389"),
        ],
        protocol_tasks=[
            task("020", "Kenyan visa and yellow-fever certificates", "Kwabena Owusu", 10, "DONE", evidence="S084-TR-2026-0388"),
            task(
                "021",
                "High Commission of Ghana, Nairobi — courtesy notification",
                "Akosua Mensah",
                12,
                "EXCEPTION",
                reason="Mission notified by the Ministry of Foreign Affairs directly; letter not required.",
            ),
        ],
        support_requests=[
            support("020", "S084", "Flights ACC–NBO and conference accommodation for two", "COMPLETED", -30, -11, "S084-TR-2026-0388", hour=9),
        ],
        approvals=[
            approval("020", "SUBMITTED", "Outbound conference participation for approval.", "Nana Yaw Boateng", 1, -35, 9),
            approval("021", "APPROVED", "Approved within the international travel budget.", head_name, 1, -33, 12),
        ],
        created=at(-40, 9),
        updated=at(-11, 16),
    )
    e4 = eng(
        4,
        type="BILATERAL_MEETING",
        direction="INBOUND",
        title="Bilateral meeting — Council of Legal Education, Nigeria",
        purpose="",
        partner_stakeholder_id=nigeria,
        partner_name="Council of Legal Education (Nigeria)",
        owner="Yaw Darko",
        host="Registrar, CLET",
        venue="CLET Head Office, Accra — Council Chamber",
        start_at=at(41, 10),
        end_at=at(41, 13),
        status="DRAFT",
        created=at(-1, 15),
        updated=at(-1, 15),
    )
    e5 = eng(
        5,
        type="DELEGATION",
        direction="INBOUND",
        title="Study visit — Kenya School of Law faculty delegation",
        purpose="Peer learning on bar examination administration and the professional law course curriculum.",
        partner_stakeholder_id=kenya,
        partner_name="Kenya School of Law",
        owner="Akosua Mensah",
        host="Director, Ghana School of Law",
        venue="Ghana School of Law, Makola — Senate Room",
        start_at=at(-13, 9),
        end_at=at(-12, 16),
        status="COMPLETED",
        checklist_version=2,
        agenda_ref="S003-DOC-2026-11402",
        briefing_pack_ref="S003-DOC-2026-11415",
        delegation=[
            member("030", "Dr. Henry Kibet", "Head of delegation — Director/CEO", "Kenya School of Law", "Kenyan", "con-063", "S084-TR-2026-0301"),
            member("031", "Wanjiru Kamau", "Head, Academic Affairs", "Kenya School of Law", "Kenyan", None, "S084-TR-2026-0302"),
            member("032", "Otieno Achieng", "Examinations lead", "Kenya School of Law", "Kenyan", None, "S084-TR-2026-0303"),
        ],
        protocol_tasks=[task("030", "Campus tour and lecture observation schedule", "Efua Asante", -16, "DONE", evidence="S003-DOC-2026-11420")],
        follow_ups=[
            follow_up("030", "Share bar examination moderation framework", "Yaw Darko", -3, "OPEN"),
            follow_up("031", "Draft MOU on faculty exchange for S082 review", "Akosua Mensah", 14, "OPEN"),
            follow_up("032", "Send thank-you letter to the Director/CEO", "Efua Asante", -8, "DONE", mandatory=False),
        ],
        support_requests=[
            support("030", "S084", "Airport transfers and guest-house accommodation", "COMPLETED", -30, -12, "S084-TR-2026-0301", hour=9),
            support("031", "S078", "Welcome reception at the Ghana School of Law", "COMPLETED", -25, -13, "S078-EV-2026-0220", hour=9),
        ],
        approvals=[
            approval("030", "SUBMITTED", "Study visit programme for approval.", "Akosua Mensah", 1, -28, 9),
            approval("031", "APPROVED", "Approved.", head_name, 1, -27),
        ],
        created=at(-32, 9),
        updated=at(-12, 18),
    )
    e6 = eng(
        6,
        type="COURTESY_CALL",
        direction="INBOUND",
        title="Courtesy call — Embassy of Japan (JICA rule-of-law programme)",
        purpose="Discuss JICA support for the CLET digital law library and continuing legal education.",
        partner_stakeholder_id=japan,
        partner_name="Embassy of Japan in Ghana",
        owner="Yaw Darko",
        host="Director-General, CLET",
        venue="Director-General's Office, CLET Head Office",
        start_at=at(-45, 10),
        end_at=at(-45, 11),
        status="CLOSED",
        agenda_ref="S003-DOC-2026-10977",
        briefing_pack_ref="S003-DOC-2026-10981",
        minutes_ref="S003-DOC-2026-11015",
        final_report_ref="S003-DOC-2026-11040",
        delegation=[member("040", "H.E. Mochizuki Hisanobu", "Ambassador", "Embassy of Japan in Ghana", "Japanese", "con-019")],
        protocol_tasks=[task("040", "Protocol briefing for the Director-General", "Efua Asante", -47, "DONE", evidence="S003-DOC-2026-10981")],
        follow_ups=[
            follow_up("040", "Submit concept note for the digital law library", "Nana Yaw Boateng", -30, "DONE"),
            follow_up(
                "041",
                "Arrange JICA site visit to the library",
                "Yaw Darko",
                -35,
                "EXCEPTION",
                reason="JICA deferred site visits to the next fiscal year; approved by the Director-General.",
            ),
        ],
        approvals=[
            approval("040", "SUBMITTED", "Courtesy call request from the Embassy.", "Yaw Darko", 1, -55, 9),
            approval("041", "APPROVED", "Approved.", head_name, 1, -54, 10),
        ],
        created=at(-58, 9),
        updated=at(-28, 16),
    )
    e7 = eng(
        7,
        type="DELEGATION",
        direction="OUTBOUND",
        title="Outbound study tour — Institut Supérieur de la Magistrature, Rabat",
        purpose="Benchmark judicial and legal practitioner training models ahead of the CLET curriculum review.",
        partner_stakeholder_id=morocco,
        partner_name="Embassy of the Kingdom of Morocco",
        owner="Nana Yaw Boateng",
        host="Institut Supérieur de la Magistrature",
        venue="ISM Campus, Rabat",
        start_at=at(62, 9),
        end_at=at(66, 17),
        time_zone="Africa/Casablanca",
        status="RETURNED",
        approvals=[
            approval("070", "SUBMITTED", "Study tour proposal.", "Nana Yaw Boateng", 1, -6, 9),
            approval("071", "RETURNED", "Add the delegation list and a costed S084 travel request before resubmitting.", head_name, 1, -5, 15),
        ],
        created=at(-7, 9),
        updated=at(-5, 15),
    )
    # Extra records (not in the frontend mock) so every status in the state model is demonstrable.
    e8 = eng(
        8,
        type="VIP_VISIT",
        direction="INBOUND",
        title="High Commissioner's visit — legal aid training partnership",
        purpose="Site visit to the Ghana School of Law to review the joint legal aid clinic training programme.",
        partner_stakeholder_id=uk,
        partner_name="British High Commission, Accra",
        owner="Akosua Mensah",
        host="Director-General, CLET",
        venue="Ghana School of Law, Makola — Senate Room",
        start_at=at(0, 8),
        end_at=at(0, 17),
        status="IN_PROGRESS",
        checklist_version=2,
        agenda_ref="S003-DOC-2026-12010",
        briefing_pack_ref="S003-DOC-2026-12018",
        version=2,
        delegation=[
            member("050", "H.E. Harriet Lawson", "High Commissioner", "British High Commission, Accra", "British"),
            member("051", "Daniel Osei", "Political & Development Officer", "British High Commission, Accra", "Ghanaian"),
        ],
        protocol_tasks=[
            task("050", "Reception at the main gate and escort", "Kwabena Owusu", -1, "DONE", evidence="S003-DOC-2026-12025"),
            task("051", "Photography and press accreditation", "Efua Asante", 0, "OPEN", mandatory=False),
        ],
        follow_ups=[follow_up("050", "Circulate the joint communiqué", "Akosua Mensah", 5, "OPEN")],
        support_requests=[support("050", "S078", "Lunch reception for 25 guests", "COMPLETED", -12, -3, "S078-EV-2026-0244", hour=9)],
        approvals=[
            approval("080", "SUBMITTED", "Visit plan for approval.", "Akosua Mensah", 1, -15, 9),
            approval("081", "APPROVED", "Approved.", head_name, 1, -14),
        ],
        created=at(-18, 9),
        updated=at(-1, 17),
    )
    e9 = eng(
        9,
        type="BILATERAL_MEETING",
        direction="OUTBOUND",
        title="Bilateral — Law Society of Kenya, Nairobi (mutual recognition of CPD)",
        purpose="Explore mutual recognition of continuing professional development credits between the two professional bodies.",
        partner_name="Law Society of Kenya",
        owner="Nana Yaw Boateng",
        host="Law Society of Kenya",
        venue="LSK Offices, Nairobi",
        start_at=at(28, 9),
        end_at=at(28, 12),
        time_zone="Africa/Nairobi",
        status="SUBMITTED",
        approvals=[approval("090", "SUBMITTED", "Proposal ready for review.", "Nana Yaw Boateng", 1, -1, 16)],
        created=at(-3, 9),
        updated=at(-1, 16),
    )
    e10 = eng(
        10,
        type="CONFERENCE",
        direction="INBOUND",
        title="West African Legal Education Forum (hosted by CLET)",
        purpose="Regional forum for heads of law schools; cancelled after the host venue withdrew.",
        partner_name="West African Law Schools Network",
        owner="Yaw Darko",
        host="Director-General, CLET",
        venue="Accra International Conference Centre",
        start_at=at(-20, 9),
        end_at=at(-18, 17),
        status="CANCELLED",
        approvals=[
            approval("100", "SUBMITTED", "Forum plan for approval.", "Yaw Darko", 1, -50, 9),
            approval("101", "CANCELLED", "Venue withdrawn; forum postponed to next year.", "Yaw Darko", 1, -25, 13),
        ],
        created=at(-52, 9),
        updated=at(-25, 13),
    )
    session.add_all([e1, e2, e3, e4, e5, e6, e7, e8, e9, e10])
    await session.flush()

    def hist(actor_id, actor_name, event, when, version=1, comment=""):
        return {"event": event, "actorId": actor_id, "actor": actor_name, "comment": comment, "version": version, "at": iso(when, 10)}

    def cor(seq: int, **kw) -> IrCorrespondence:
        created = kw.pop("created")
        updated = kw.pop("updated")
        return IrCorrespondence(
            reference=cor_ref(seq),
            classification=kw.pop("classification", "INTERNAL"),
            language=kw.pop("language", "EN"),
            history=kw.pop("history", []),
            version=kw.pop("version", 1),
            created_at=created,
            updated_at=updated,
            **kw,
        )

    en2, fr1, ar1 = templates["en2"], templates["fr1"], templates["ar1"]
    dg = "Director-General, CLET"
    council = "Council for Legal Education and Training"

    letters = [
        cor(
            1,
            direction="INBOUND",
            engagement_id=e1.id,
            sender="ECOWAS Commission, Abuja",
            recipient=dg,
            subject="Proposed working visit on harmonisation of legal education",
            classification="CONFIDENTIAL",
            owner="Akosua Mensah",
            received_at=day(-24),
            response_deadline=day(3),
            status="AWAITING_RESPONSE",
            body="The Commission proposes a two-day working visit by the Commissioner for Human Development…",
            document_ref="S003-DOC-2026-11650",
            history=[hist(letters_id, letters_name, "CREATED", -24), hist(letters_id, letters_name, "AWAITING_RESPONSE", -20)],
            created=at(-24, 11),
            updated=at(-20, 9),
        ),
        cor(
            2,
            direction="INBOUND",
            engagement_id=e2.id,
            sender="Embassy of the Kingdom of Morocco, Accra",
            recipient=dg,
            subject="Demande de visite de courtoisie de S.E. l’Ambassadeur",
            language="FR",
            owner="Yaw Darko",
            received_at=day(-11),
            response_deadline=day(-4),
            status="AWAITING_RESPONSE",
            body="L’Ambassade du Royaume du Maroc présente ses compliments au Conseil et sollicite une visite de courtoisie…",
            translation_ref="TRN-MAN-2026-044 (reviewed by E. Asante)",
            document_ref="S003-DOC-2026-11880",
            history=[hist(letters_id, letters_name, "CREATED", -11), hist(letters_id, letters_name, "AWAITING_RESPONSE", -10)],
            created=at(-11, 10),
            updated=at(-10, 9),
        ),
        cor(
            3,
            direction="INBOUND",
            sender="Embassy of the Arab Republic of Egypt, Accra",
            recipient=dg,
            subject="منح تدريبية في المعهد القومي للدراسات القضائية",
            language="AR",
            owner="Efua Asante",
            received_at=day(-9),
            response_deadline=day(-1),
            status="RECEIVED",
            body="تهدي سفارة جمهورية مصر العربية أطيب تحياتها إلى المجلس، وتتشرف بإبلاغه بتوفر منح تدريبية…",
            document_ref="S003-DOC-2026-11897",
            history=[hist(letters_id, letters_name, "CREATED", -9)],
            created=at(-9, 12),
            updated=at(-9, 12),
        ),
        cor(
            4,
            direction="OUTBOUND",
            engagement_id=e1.id,
            sender=council,
            recipient="Prof. Fatou Sarr Sow, Commissioner for Human Development",
            subject="Working visit on harmonisation of legal education",
            classification="CONFIDENTIAL",
            owner="Akosua Mensah",
            response_deadline=day(6),
            status="APPROVED",
            body=(
                "Your Excellency Prof. Fatou Sarr Sow, Commissioner for Human Development,\n\nThe Council for Legal "
                "Education and Training presents its compliments and has the honour to confirm the arrangements for the "
                "ECOWAS Commission delegation on regional legal education, concerning the working visit on harmonisation "
                "of legal education.\n\nThe detailed programme and protocol arrangements are enclosed. Our International "
                "Relations & Protocols Unit remains at your disposal for any further information.\n\nThe Council for Legal "
                "Education and Training avails itself of this opportunity to renew the assurances of its highest "
                f"consideration.\n\nAccra, {_en(-9)}"
            ),
            template_id=en2.id,
            template_version=2,
            document_ref="S003-DOC-2026-11870",
            approved_version=2,
            approved_by_id=head_id,
            history=[
                hist(letters_id, letters_name, "CREATED", -9),
                hist(letters_id, letters_name, "IN_REVIEW", -8, 2),
                hist(head_id, head_name, "APPROVED", -7, 2),
            ],
            version=2,
            created=at(-9, 9),
            updated=at(-7, 14),
        ),
        cor(
            5,
            direction="OUTBOUND",
            sender="مجلس التعليم والتدريب القانوني",
            recipient="سفير جمهورية مصر العربية",
            subject="منح تدريبية في المعهد القومي للدراسات القضائية",
            language="AR",
            owner="Efua Asante",
            status="IN_REVIEW",
            body=(
                "سعادة سفير جمهورية مصر العربية،\n\nيهدي مجلس التعليم والتدريب القانوني أطيب تحياته، ويتشرف بأن يؤكد "
                "الترتيبات الخاصة بـ ترشيح المتدربين بشأن منح تدريبية في المعهد القومي للدراسات القضائية.\n\nمرفق طيه "
                "البرنامج التفصيلي والترتيبات البروتوكولية. وتظل وحدة العلاقات الدولية والمراسم لدينا رهن إشارتكم لأي "
                "معلومات إضافية.\n\nويغتنم مجلس التعليم والتدريب القانوني هذه الفرصة ليعرب لكم عن فائق التقدير "
                f"والاحترام.\n\nأكرا، في {_ar(-5)}"
            ),
            template_id=ar1.id,
            template_version=1,
            translation_ref="TRN-MAN-2026-051 (reviewed by K. Benjelloun, pending S086)",
            history=[hist(letters_id, letters_name, "CREATED", -5), hist(letters_id, letters_name, "IN_REVIEW", -4)],
            created=at(-5, 9),
            updated=at(-4, 10),
        ),
        cor(
            6,
            direction="OUTBOUND",
            engagement_id=e2.id,
            sender="Conseil pour l’Éducation et la Formation Juridiques",
            recipient="S.E. Mme Imane Ouaadil, Ambassadeur du Royaume du Maroc",
            subject="Visite de courtoisie",
            language="FR",
            owner="Yaw Darko",
            status="DRAFT",
            body=(
                "Excellence S.E. Mme Imane Ouaadil, Ambassadeur du Royaume du Maroc,\n\nLe Conseil pour l’Éducation et la "
                "Formation Juridiques présente ses compliments et a l’honneur de confirmer les dispositions relatives à "
                "la visite de courtoisie de Son Excellence, concernant la visite de courtoisie prévue au bureau du "
                "Directeur général.\n\nLe programme détaillé et les dispositions protocolaires sont joints à la présente. "
                "Notre Unité des Relations Internationales et du Protocole reste à votre disposition pour toute "
                "information complémentaire.\n\nLe Conseil pour l’Éducation et la Formation Juridiques saisit cette "
                "occasion pour vous renouveler l’assurance de sa très haute considération.\n\n"
                f"Fait à Accra, le {_fr(-2)}"
            ),
            template_id=fr1.id,
            template_version=1,
            approved_version=2,
            approved_by_id=head_id,
            history=[
                hist(letters_id, letters_name, "CREATED", -8),
                hist(letters_id, letters_name, "IN_REVIEW", -6, 2),
                hist(head_id, head_name, "APPROVED", -5, 2),
                hist(letters_id, letters_name, "UPDATED", -2, 3, "Material change: approval invalidated."),
            ],
            version=3,
            created=at(-8, 9),
            updated=at(-2, 16),
        ),
        cor(
            7,
            direction="OUTBOUND",
            engagement_id=e5.id,
            sender=council,
            recipient="Dr. Henry Kibet, Director/CEO, Kenya School of Law",
            subject="Thank you for the faculty study visit",
            classification="PUBLIC",
            owner="Efua Asante",
            sent_at=at(-9, 15),
            response_deadline=day(12),
            status="AWAITING_RESPONSE",
            body="Dear Dr. Kibet,\n\nOn behalf of the Council, thank you for leading the faculty delegation…",
            document_ref="S003-DOC-2026-11530",
            dispatch_ref="S074-MSG-2026-08812",
            approved_version=1,
            approved_by_id=head_id,
            history=[
                hist(letters_id, letters_name, "CREATED", -11),
                hist(letters_id, letters_name, "IN_REVIEW", -10),
                hist(head_id, head_name, "APPROVED", -10),
                hist(letters_id, letters_name, "DISPATCHED", -9),
                hist(letters_id, letters_name, "AWAITING_RESPONSE", -9),
            ],
            created=at(-11, 9),
            updated=at(-9, 15),
        ),
        cor(
            8,
            direction="INBOUND",
            engagement_id=e6.id,
            sender="Embassy of Japan in Ghana",
            recipient=dg,
            subject="Request for courtesy call — JICA rule-of-law programme",
            owner="Yaw Darko",
            received_at=day(-62),
            response_deadline=day(-55),
            status="CLOSED",
            body="The Embassy of Japan presents its compliments and requests a courtesy call…",
            document_ref="S003-DOC-2026-10940",
            history=[
                hist(letters_id, letters_name, "CREATED", -62),
                hist(letters_id, letters_name, "AWAITING_RESPONSE", -60),
                hist(letters_id, letters_name, "CLOSED", -45),
            ],
            created=at(-62, 11),
            updated=at(-45, 12),
        ),
        # Extra records (not in the frontend mock) so every correspondence state is on screen.
        cor(
            9,
            direction="OUTBOUND",
            engagement_id=e8.id,
            sender=council,
            recipient="H.E. Harriet Lawson, British High Commissioner",
            subject="Programme for the High Commissioner's visit",
            owner="Akosua Mensah",
            status="RETURNED",
            body="Your Excellency,\n\nPlease find the draft programme for your visit…",
            template_id=en2.id,
            template_version=2,
            history=[
                hist(letters_id, letters_name, "CREATED", -13),
                hist(letters_id, letters_name, "IN_REVIEW", -12),
                hist(head_id, head_name, "RETURNED", -11, 1, "Insert the confirmed arrival time and the security arrangements."),
            ],
            created=at(-13, 9),
            updated=at(-11, 15),
        ),
        cor(
            10,
            direction="OUTBOUND",
            sender=council,
            recipient="Registrar, Nigerian Law School",
            subject="Invitation to the bar examination moderation workshop",
            owner="Efua Asante",
            sent_at=at(-1, 11),
            response_deadline=day(14),
            status="DISPATCHED",
            body="Dear Registrar,\n\nThe Council has the honour to invite the Law School to the moderation workshop…",
            document_ref="S003-DOC-2026-12044",
            dispatch_ref="S074-MSG-2026-09104",
            approved_version=1,
            approved_by_id=head_id,
            history=[
                hist(letters_id, letters_name, "CREATED", -4),
                hist(letters_id, letters_name, "IN_REVIEW", -3),
                hist(head_id, head_name, "APPROVED", -2),
                hist(letters_id, letters_name, "DISPATCHED", -1),
            ],
            created=at(-4, 9),
            updated=at(-1, 11),
        ),
        cor(
            11,
            direction="INBOUND",
            engagement_id=e3.id,
            sender="Commonwealth Legal Education Association, Nairobi",
            recipient=dg,
            subject="Confirmation of panel slot at the Pan-African conference",
            classification="PUBLIC",
            owner="Nana Yaw Boateng",
            received_at=day(-30),
            response_deadline=day(-23),
            status="RESPONDED",
            body="We are pleased to confirm your panel slot on practical legal training standards…",
            document_ref="S003-DOC-2026-11620",
            history=[
                hist(letters_id, letters_name, "CREATED", -30),
                hist(letters_id, letters_name, "AWAITING_RESPONSE", -29),
                hist(letters_id, letters_name, "RESPONDED", -26),
            ],
            created=at(-30, 10),
            updated=at(-26, 14),
        ),
    ]
    session.add_all(letters)

    def gift(**kw) -> IrGift:
        created = kw.pop("created")
        return IrGift(recorded_by=officer_id, created_at=created, **kw)

    gifts = [
        gift(direction="RECEIVED", engagement_id=e5.id, giver="Dr. Henry Kibet, Kenya School of Law", recipient="Director, Ghana School of Law", description="Carved Maasai shield plaque with Kenya School of Law crest", gift_date=day(-12), value_known=False, s011_status="FAILED", flag_attempts=2, created=at(-12, 17)),
        gift(direction="RECEIVED", engagement_id=e5.id, giver="Kenya School of Law", recipient="CLET Library", description="Bound set of Kenya Law Reports (2019–2024)", gift_date=day(-12), value_known=True, value=180, currency="USD", s011_status="PENDING", flag_attempts=1, created=at(-12, 17)),
        gift(direction="GIVEN", engagement_id=e5.id, giver="Director, Ghana School of Law", recipient="Dr. Henry Kibet, Kenya School of Law", description="Kente stole with CLET crest", gift_date=day(-12), value_known=True, value=850, currency="GHS", s011_status="NOT_REQUIRED", created=at(-12, 17)),
        gift(direction="RECEIVED", engagement_id=e6.id, giver="H.E. Mochizuki Hisanobu, Embassy of Japan", recipient="Director-General, CLET", description="Wajima lacquerware document box", gift_date=day(-45), value_known=True, value=45000, currency="JPY", s011_status="ACKNOWLEDGED", s011_ref="S011-GF-2026-00731", flag_attempts=1, created=at(-45, 13)),
        gift(direction="GIVEN", engagement_id=e6.id, giver="Director-General, CLET", recipient="H.E. Mochizuki Hisanobu, Embassy of Japan", description="Framed Adinkra print “Nyansapo” (wisdom knot)", gift_date=day(-45), value_known=True, value=1200, currency="GHS", s011_status="NOT_REQUIRED", created=at(-45, 13)),
        gift(direction="RECEIVED", engagement_id=e8.id, giver="H.E. Harriet Lawson, British High Commission", recipient="Director-General, CLET", description="Set of Commonwealth Law Reports (leather bound)", gift_date=day(0), value_known=True, value=320, currency="GBP", s011_status="PENDING", flag_attempts=1, created=at(0, 12)),
    ]
    session.add_all(gifts)
