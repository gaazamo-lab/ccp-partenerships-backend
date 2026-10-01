"""Demo dataset for S081 Stakeholder CRM, audience segments and S082 MOU lifecycle.

Ported from the partner-portal mock seeds (`features/stakeholders/data/mockCrmData.ts`,
`features/partnerships/data/mockPartnershipData.ts`) and extended so every UI state
(overdue obligations, expiring/expired/terminated agreements, failed alerts, blocked
screening, withdrawn/expired consent, ...) can be demonstrated.

Mock dates were authored around 2026-09-26; every date here is shifted so that day maps
to *today*, keeping the data fresh. `seed_demo` (scripts/seed.py) creates the three
shell organisations Ghana Bar Association, University of Ghana School of Law and Legal
Futures Foundation (other modules reference them); this module adopts them by name.

Idempotent (marker: the "Accredited law faculties" segment) and never commits.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime, time

from sqlalchemy import select

from app.models.partnerships import (
    ObligationProgressNote,
    PartnershipAgreement,
    PartnershipHistory,
    PartnershipObligation,
    PartnershipRenewal,
    PartnershipRenewalAlert,
    PartnershipReview,
)
from app.models.stakeholders import (
    Segment,
    Stakeholder,
    StakeholderContact,
    StakeholderEngagement,
)

MARKER_SEGMENT = "Accredited law faculties"
ANCHOR = dt.date(2026, 9, 26)
TODAY = dt.date.today()
RECIPIENTS = ["partnerships@clet.gov.gh", "registrar@clet.gov.gh"]


def R(iso: str | None) -> dt.date | None:
    """Shift a mock-era ISO date so the mock's 'today' (2026-09-26) is the real today."""
    if iso is None:
        return None
    return TODAY + (dt.date.fromisoformat(iso) - ANCHOR)


def ago(days: int) -> dt.date:
    return TODAY - dt.timedelta(days=days)


def ahead(days: int) -> dt.date:
    return TODAY + dt.timedelta(days=days)


def stamp(day: dt.date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=dt.UTC)


# ── Stakeholders ──


def _contact(**fields) -> dict:
    base = {
        "consent": "Consented",
        "consent_date": R("2026-03-14"),
        "consent_channel": "Form",
        "screening": "Not required",
        "screening_record": None,
        "phone": "",
        "active": True,
    }
    base.update(fields)
    return base


def _decision(outcome: str, reviewer: str, reviewed: dt.date, notes: str, case_ref: str | None) -> dict:
    return {
        "outcome": outcome,
        "reviewer": reviewer,
        "reviewedAt": stamp(reviewed, 11, 30).isoformat(),
        "notes": notes,
        "caseRef": case_ref,
    }


def _eng(type_: str, title: str, summary: str, iso: str, source: str = "Partner CRM") -> dict:
    return {"type": type_, "title": title, "summary": summary, "date": R(iso), "source": source}


STAKEHOLDERS: list[dict] = [
    {
        "name": "Ghana Bar Association",
        "short_name": "GBA",
        "category": "Professional body",
        "owner": "Nana Asante",
        "status": "MOU linked",
        "health": "Strong",
        "pipeline_stage": "MOU",
        "location": "Accra, Ghana",
        "website": "ghanabar.org",
        "description": "National professional association and a key partner in legal education standards, "
        "practitioner engagement, and continuing professional development.",
        "contacts": [
            _contact(
                name="Ama Owusu",
                role="Executive Secretary",
                email="ama.owusu@ghanabar.org",
                phone="+233 20 555 0142",
            ),
            _contact(
                name="Kofi Mensah",
                role="Programme Director",
                email="kofi.mensah@ghanabar.org",
                phone="+233 24 555 0198",
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Quarterly partnership review",
                "Agreed Q4 priorities for continuing legal education and practitioner outreach.",
                "2026-09-12",
            ),
            _eng(
                "Event",
                "Legal Education Forum registration",
                "Four GBA delegates registered for the national forum.",
                "2026-08-28",
                "S078 Events",
            ),
            _eng(
                "MOU",
                "Professional development MOU advanced",
                "Draft moved to legal review with both institutions.",
                "2026-08-14",
                "S082 MOU Tracker",
            ),
            _eng(
                "Campaign",
                "August stakeholder briefing",
                "Briefing delivered to both consented contacts.",
                "2026-08-02",
                "S075 Newsletter",
            ),
            _eng(
                "Call",
                "CPD accreditation follow-up",
                "Confirmed the GBA CPD committee will review the joint module list in July.",
                "2026-06-18",
            ),
        ],
    },
    {
        "name": "Embassy of France in Ghana",
        "short_name": "FR",
        "category": "Embassy",
        "owner": "Akua Boateng",
        "status": "Screening pending",
        "health": "Healthy",
        "pipeline_stage": "Prospect",
        "location": "Accra, Ghana",
        "website": "gh.ambafrance.org",
        "description": "Diplomatic partner supporting international legal education and exchange programmes.",
        "contacts": [
            _contact(
                name="Claire Martin",
                role="Cooperation Attaché",
                email="claire.martin@diplomatie.gouv.fr",
                phone="+233 30 221 4550",
                screening="Pending",
            ),
            _contact(
                name="Marc Dupont",
                role="Cultural Counsellor",
                email="marc.dupont@diplomatie.gouv.fr",
                phone="+233 30 221 4561",
                consent_date=R("2026-05-06"),
                consent_channel="Letter",
                screening="Cleared",
                screening_record=_decision(
                    "Cleared",
                    "Adwoa Sarpong",
                    ago(80),
                    "Diplomatic accreditation verified; no adverse findings.",
                    "S203-2026-0214",
                ),
            ),
        ],
        "engagements": [
            _eng(
                "Correspondence",
                "Exchange programme enquiry received",
                "Letter from the Cooperation Service proposing a francophone legal exchange.",
                "2026-09-10",
                "S089 Correspondence",
            ),
        ],
    },
    {
        "name": "University of Ghana School of Law",
        "short_name": "UG",
        "category": "University",
        "owner": "Nana Asante",
        "status": "Active",
        "health": "Strong",
        "pipeline_stage": "Engaged",
        "location": "Legon, Ghana",
        "website": "law.ug.edu.gh",
        "description": "Accredited law faculty and a central partner in professional legal education.",
        "contacts": [
            _contact(
                name="Prof. Esi Darko",
                role="Dean of Law",
                email="e.darko@ug.edu.gh",
                phone="+233 30 250 0381",
                consent_date=R("2026-01-20"),
                consent_channel="Email",
            ),
            _contact(
                name="Yaw Frimpong",
                role="Faculty Registrar",
                email="y.frimpong@ug.edu.gh",
                phone="+233 30 250 0390",
                consent="Not recorded",
                consent_date=None,
                consent_channel=None,
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Accreditation readiness workshop",
                "Walked the faculty through the 2027 accreditation evidence pack.",
                "2026-09-08",
            ),
            _eng(
                "Email",
                "Curriculum mapping shared",
                "Sent the professional-course curriculum map for faculty comment.",
                "2026-07-22",
            ),
        ],
    },
    {
        "name": "Ministry of Justice and Attorney-General",
        "short_name": "MOJ",
        "category": "Government",
        "owner": "Efua Kwarteng",
        "status": "Active",
        "health": "Healthy",
        "pipeline_stage": "Negotiation",
        "location": "Accra, Ghana",
        "website": "mojagd.gov.gh",
        "description": "Government stakeholder for legal policy, statutory oversight, and institutional coordination.",
        "contacts": [
            _contact(
                name="Abena Sarpong",
                role="Chief Director",
                email="abena.sarpong@mojagd.gov.gh",
                phone="+233 30 266 5051",
                consent_date=R("2026-02-05"),
                consent_channel="Letter",
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Legal Education Act regulations briefing",
                "Reviewed the draft L.I. timetable with the Chief Director.",
                "2026-09-03",
            ),
        ],
    },
    {
        "name": "Ford Foundation West Africa",
        "short_name": "FF",
        "category": "Donor",
        "owner": "Akua Boateng",
        "status": "Screening pending",
        "health": "Healthy",
        "pipeline_stage": "Prospect",
        "location": "Lagos, Nigeria",
        "website": "fordfoundation.org",
        "description": "Philanthropic organisation supporting justice, learning, and institutional development.",
        "contacts": [
            _contact(
                name="Bisi Adeyemi",
                role="Programme Officer",
                email="b.adeyemi@fordfoundation.org",
                phone="+234 80 5555 0123",
                consent="Not recorded",
                consent_date=None,
                consent_channel=None,
                screening="Review required",
                screening_record=_decision(
                    "Review required",
                    "Adwoa Sarpong",
                    ago(20),
                    "Beneficial-ownership disclosure incomplete; awaiting foundation's compliance statement.",
                    "S203-2026-0231",
                ),
            ),
            _contact(
                name="Ngozi Eze",
                role="Grants Manager",
                email="n.eze@fordfoundation.org",
                phone="+234 80 5555 0188",
                consent_date=R("2026-06-02"),
                consent_channel="Email",
                screening="Cleared",
                screening_record=_decision(
                    "Cleared",
                    "Adwoa Sarpong",
                    ago(75),
                    "Standard donor due diligence completed for this contact.",
                    "S203-2026-0198",
                ),
            ),
        ],
        "engagements": [
            _eng(
                "Event",
                "Access to justice donor roundtable",
                "Programme team attended the S078 roundtable; follow-up held pending screening.",
                "2026-08-29",
                "S078 Events",
            ),
        ],
    },
    {
        "name": "Judicial Service of Ghana",
        "short_name": "JSG",
        "category": "Judiciary",
        "owner": "Efua Kwarteng",
        "status": "Active",
        "health": "Strong",
        "pipeline_stage": "Engaged",
        "location": "Accra, Ghana",
        "website": "judicial.gov.gh",
        "description": "Institutional partner for court-facing legal education and judicial engagement.",
        "contacts": [
            _contact(
                name="Kwabena Owusu-Ansah",
                role="Judicial Secretary",
                email="k.owusuansah@judicial.gov.gh",
                phone="+233 30 266 3200",
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Pupillage placement planning",
                "Agreed court placement capacity for the next pupillage cohort.",
                "2026-08-21",
            ),
        ],
    },
    {
        "name": "Graphic Communications Group",
        "short_name": "GCG",
        "category": "Media",
        "owner": "Kojo Addo",
        "status": "MOU linked",
        "health": "Healthy",
        "pipeline_stage": "MOU",
        "location": "Accra, Ghana",
        "website": "graphic.com.gh",
        "description": "National newspaper group; legal affairs desk covers CLET announcements.",
        "contacts": [
            _contact(
                name="Adwoa Nyarko",
                role="Legal Affairs Editor",
                email="a.nyarko@graphic.com.gh",
                phone="+233 24 555 0711",
                consent_date=R("2026-04-02"),
                consent_channel="Email",
            ),
            _contact(
                name="Samuel Tetteh",
                role="Senior Reporter",
                email="s.tetteh@graphic.com.gh",
                phone="+233 20 555 0733",
                consent="Withdrawn",
                consent_date=R("2026-08-11"),
                consent_channel="Email",
            ),
        ],
        "engagements": [
            _eng(
                "Campaign",
                "Entrance examination results release",
                "Press pack issued to the legal affairs desk.",
                "2026-07-30",
                "S075 Newsletter",
            ),
            _eng(
                "MOU",
                "Media partnership renewal window opened",
                "Renewal alerts scheduled for the media partnership.",
                "2026-07-01",
                "S082 MOU Tracker",
            ),
        ],
    },
    {
        "name": "Nigerian Law School",
        "short_name": "NLS",
        "category": "Peer institution",
        "owner": "Akua Boateng",
        "status": "Active",
        "health": "At risk",
        "pipeline_stage": "Dormant",
        "location": "Abuja, Nigeria",
        "website": "nigerianlawschool.edu.ng",
        "description": "Peer professional law school; benchmarking partner for the Bar course and assessment.",
        "contacts": [
            _contact(
                name="Chinedu Okafor",
                role="Director of Academics",
                email="c.okafor@nigerianlawschool.edu.ng",
                phone="+234 80 5555 0456",
                consent="Expired",
                consent_date=R("2024-03-01"),
                consent_channel="Form",
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Assessment benchmarking visit",
                "Compared Bar Part II assessment models; no follow-up since.",
                "2026-03-17",
            ),
        ],
    },
    # Adopts the shell created by seed_demo (donor prospect, screening not yet started).
    {
        "name": "Legal Futures Foundation",
        "short_name": "LFF",
        "category": "Donor",
        "owner": "Nana Asante",
        "status": "Screening pending",
        "health": "Healthy",
        "pipeline_stage": "Prospect",
        "location": "London, United Kingdom",
        "website": "legalfutures.org",
        "description": "Philanthropic funder of legal education.",
        "contacts": [
            _contact(
                name="Helen Carter",
                role="Programme Director",
                email="helen@legalfutures.org",
                phone="+44 20 7946 0321",
                consent="Not recorded",
                consent_date=None,
                consent_channel=None,
                screening="Pending",
            ),
        ],
        "engagements": [
            _eng(
                "Email",
                "Introductory funding enquiry",
                "Foundation asked about co-funding the clinical legal education pilot.",
                "2026-09-14",
            ),
        ],
    },
    # Extras that make the remaining UI states demonstrable.
    {
        "name": "Kenya School of Law",
        "short_name": "KSL",
        "category": "Peer institution",
        "owner": "Efua Kwarteng",
        "status": "Active",
        "health": "Healthy",
        "pipeline_stage": "Negotiation",
        "location": "Nairobi, Kenya",
        "website": "ksl.ac.ke",
        "description": "Regional peer institution; earlier exchange MOU ended by mutual agreement and a successor "
        "framework is under discussion.",
        "contacts": [
            _contact(
                name="Wanjiru Kamau",
                role="Director of Programmes",
                email="w.kamau@ksl.ac.ke",
                phone="+254 20 555 0188",
                consent_date=R("2026-05-19"),
                consent_channel="In person",
            ),
        ],
        "engagements": [
            _eng(
                "Meeting",
                "Successor framework scoping call",
                "Explored a lighter-touch exchange framework after the 2024 MOU closed.",
                "2026-09-01",
            ),
            _eng(
                "MOU",
                "Exchange MOU terminated by mutual agreement",
                "Closed with archive references recorded.",
                "2026-06-30",
                "S082 MOU Tracker",
            ),
        ],
    },
    {
        "name": "Commonwealth Legal Education Association",
        "short_name": "CLEA",
        "category": "International body",
        "owner": "Akua Boateng",
        "status": "Inactive",
        "health": "At risk",
        "pipeline_stage": "Dormant",
        "location": "London, United Kingdom",
        "website": "clea-commonwealth.org",
        "description": "International body; relationship paused after screening could not be completed.",
        "contacts": [
            _contact(
                name="Ian Whitfield",
                role="Secretary-General",
                email="i.whitfield@clea-commonwealth.org",
                phone="+44 20 7946 0555",
                consent="Withdrawn",
                consent_date=R("2026-06-10"),
                consent_channel="Email",
                screening="Rejected",
                screening_record=_decision(
                    "Rejected",
                    "Adwoa Sarpong",
                    ago(60),
                    "Adverse media findings could not be resolved with the association.",
                    "S203-2026-0187",
                ),
            ),
            _contact(
                name="Priya Nair",
                role="Programmes Coordinator",
                email="p.nair@clea-commonwealth.org",
                phone="+44 20 7946 0556",
                consent="Not recorded",
                consent_date=None,
                consent_channel=None,
                screening="Pending",
                active=False,
            ),
        ],
        "engagements": [
            _eng(
                "Correspondence",
                "Screening outcome communicated",
                "Association informed that engagement is paused.",
                "2026-07-28",
                "S089 Correspondence",
            ),
        ],
    },
]

SEGMENTS: list[dict] = [
    {
        "name": "Accredited law faculties",
        "description": "Academic leaders and designated contacts at accredited institutions.",
        "used_by": ["S075 Newsletter", "S088 Consultations"],
        "updated": "2026-09-26",
        "criteria": {"categories": ["University"], "statuses": [], "owners": [], "consentedOnly": False},
    },
    {
        "name": "Media and press contacts",
        "description": "Verified editors, legal correspondents, and public affairs contacts.",
        "used_by": ["S075 Newsletter"],
        "updated": "2026-09-25",
        "criteria": {"categories": ["Media"], "statuses": [], "owners": [], "consentedOnly": True},
    },
    {
        "name": "International partners",
        "description": "Embassies, diplomatic missions, and international legal education bodies.",
        "used_by": ["S075 Newsletter", "S088 Consultations"],
        "updated": "2026-09-16",
        "criteria": {
            "categories": ["Embassy", "International body", "Peer institution"],
            "statuses": [],
            "owners": [],
            "consentedOnly": False,
        },
    },
    {
        "name": "Donor and philanthropic partners",
        "description": "Cleared donor contacts with current communication consent.",
        "used_by": ["S088 Consultations"],
        "updated": "2026-09-15",
        "criteria": {"categories": ["Donor"], "statuses": [], "owners": [], "consentedOnly": True},
    },
    {
        "name": "Justice sector leadership",
        "description": "Judiciary, Ministry of Justice and Bar leadership for policy consultations.",
        "used_by": ["S088 Consultations"],
        "updated": "2026-09-10",
        "criteria": {
            "categories": ["Judiciary", "Government", "Professional body"],
            "statuses": [],
            "owners": [],
            "consentedOnly": False,
        },
    },
    {
        "name": "Active MOU partners",
        "description": "Organisations with a live MOU, for partnership briefings.",
        "used_by": ["S075 Newsletter"],
        "updated": "2026-09-20",
        "criteria": {"categories": [], "statuses": ["MOU linked"], "owners": [], "consentedOnly": False},
    },
    {
        "name": "Nana Asante portfolio",
        "description": "Relationships owned by the Partnerships Manager.",
        "used_by": [],
        "updated": "2026-09-22",
        "criteria": {"categories": [], "statuses": [], "owners": ["Nana Asante"], "consentedOnly": True},
    },
]


# ── Partnerships ──


def _ob(title, description, owner, due, status, evidence=(), lead=14, escalation="Director, Strategic Partnerships", progress=()):
    return {
        "title": title,
        "description": description,
        "owner": owner,
        "due": due,
        "status": status,
        "evidence": list(evidence),
        "lead": lead,
        "escalation": escalation,
        "progress": list(progress),
    }


def _alert(milestone: int, status: str, ref: str | None = None, ack_by: str | None = None):
    return {"milestone": milestone, "status": status, "ref": ref, "ack_by": ack_by}


AGREEMENTS: list[dict] = [
    {
        "key": "mou-001",
        "stakeholder": "Ghana Bar Association",
        "parties": ["Ghana Bar Association"],
        "reference_no": 1,
        "title": "Continuing Legal Education Cooperation",
        "type": "MOU",
        "status": "ACTIVE",
        "owner": "Nana Asante",
        "effective": R("2026-08-01"),
        "expiry": R("2028-07-31"),
        "value": "Joint CLE programme delivery and practitioner engagement",
        "deliverables": ["Annual joint CLE programme", "Joint programme steering group"],
        "legal": "S136-CTR-2026-0081",
        "signed": "S003-DOC-2026-1142",
        "created": R("2026-06-14"),
        "updated": R("2026-09-12"),
        "obligations": [
            _ob(
                "Publish annual CLE programme",
                "Agree and publish the joint professional development calendar.",
                "Nana Asante",
                R("2026-10-15"),
                "IN_PROGRESS",
                progress=[("Draft calendar circulated to the GBA CPD committee.", "IN_PROGRESS", "Nana Asante", 12)],
            ),
            _ob(
                "Nominate programme steering group",
                "Each party nominates two representatives to the joint steering group.",
                "Ama Owusu",
                R("2026-09-05"),
                "COMPLETED",
                ["S003-DOC-2026-1210"],
                7,
                progress=[("Four nominees confirmed by both parties.", "COMPLETED", "Ama Owusu", 21)],
            ),
            _ob(
                "Quarterly steering group report",
                "Report on CLE delivery, attendance and feedback.",
                "Kofi Mensah",
                ago(9),
                "IN_PROGRESS",
                lead=7,
                escalation="Registrar",
                progress=[("Attendance data still awaited from two regional chapters.", "IN_PROGRESS", "Kofi Mensah", 15)],
            ),
        ],
        "alerts": [_alert(180, "SCHEDULED"), _alert(90, "SCHEDULED"), _alert(30, "SCHEDULED")],
        "reviews": [],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Nana Asante", R("2026-06-14")),
            ("STATUS_CHANGED", "Lifecycle status changed to LEGAL_REVIEW.", "Nana Asante", R("2026-06-30")),
            ("STATUS_CHANGED", "Lifecycle status changed to SIGNATURE_PENDING.", "Adwoa Sarpong", R("2026-07-20")),
            (
                "STATUS_CHANGED",
                "Lifecycle status changed to ACTIVE. Executed copy filed in S003.",
                "Nana Asante",
                R("2026-08-01"),
            ),
            ("OBLIGATION_UPDATED", "Obligation 'Nominate programme steering group' completed.", "Ama Owusu", R("2026-09-05")),
        ],
    },
    {
        "key": "mou-002",
        "stakeholder": "University of Ghana School of Law",
        "parties": ["University of Ghana School of Law", "Ministry of Justice and Attorney-General"],
        "reference_no": 2,
        "title": "Academic Standards and Faculty Development Framework",
        "type": "COOPERATION_FRAMEWORK",
        "status": "LEGAL_REVIEW",
        "owner": "Nana Asante",
        "effective": None,
        "expiry": None,
        "value": "Faculty development, curriculum consultation, and research collaboration",
        "deliverables": ["Faculty development plan", "Annual curriculum consultation report"],
        "legal": "S136-CTR-2026-0094",
        "signed": None,
        "created": R("2026-08-03"),
        "updated": R("2026-09-08"),
        "obligations": [
            _ob(
                "Draft faculty development plan",
                "Joint plan for the first year of the framework.",
                "Prof. Esi Darko",
                ahead(45),
                "NOT_STARTED",
                lead=14,
            ),
        ],
        "alerts": [],
        "reviews": [],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Nana Asante", R("2026-08-03")),
            ("STATUS_CHANGED", "Lifecycle status changed to LEGAL_REVIEW.", "Nana Asante", R("2026-09-08")),
        ],
    },
    {
        "key": "mou-003",
        "stakeholder": "Judicial Service of Ghana",
        "parties": ["Judicial Service of Ghana"],
        "reference_no": 14,
        "reference_year": 2024,
        "title": "Judicial Education and Court Attachment Programme",
        "type": "PARTNERSHIP_AGREEMENT",
        "status": "RENEWAL_DUE",
        "owner": "Efua Kwarteng",
        "effective": R("2024-01-15"),
        "expiry": R("2026-12-31"),
        "value": "Court attachment placements and judicial education exchanges",
        "deliverables": ["Annual court attachment placements", "Judicial education exchange sessions"],
        "legal": "S136-CTR-2024-0022",
        "signed": "S003-DOC-2024-0451",
        "created": R("2024-01-10"),
        "updated": R("2026-09-01"),
        "obligations": [
            _ob(
                "Confirm 2027 court attachment capacity",
                "Confirm the number of student attachment places available for 2027.",
                "Efua Kwarteng",
                R("2026-10-01"),
                "NOT_STARTED",
                escalation="Registrar",
            ),
            _ob(
                "Deliver judicial education exchange session",
                "Second exchange session of the 2026 programme.",
                "Efua Kwarteng",
                R("2026-07-15"),
                "COMPLETED",
                ["S003-DOC-2026-0977"],
                14,
                "Registrar",
                progress=[("Session delivered to 34 judges and magistrates.", "COMPLETED", "Efua Kwarteng", 70)],
            ),
        ],
        "alerts": [_alert(180, "SENT", "S074-OUTBOX-1A2B3C4D5E6F"), _alert(90, "SCHEDULED"), _alert(30, "SCHEDULED")],
        "reviews": [
            {
                "date": R("2026-08-21"),
                "reviewer": "Efua Kwarteng",
                "outcome": "ON_TRACK",
                "summary": "Court attachment targets were met. Renewal should expand regional placement capacity.",
                "start": R("2025-08-01"),
                "end": R("2026-07-31"),
                "outputs": ["48 student placements completed", "Two judicial education exchanges delivered"],
                "score": 4,
                "issues": ["Regional placement demand exceeds current capacity"],
                "recommendations": ["Add regional court placement quotas to the renewed agreement"],
                "rec": "RENEW_WITH_CHANGES",
                "next": R("2027-08-21"),
            },
            {
                "date": R("2025-08-14"),
                "reviewer": "Efua Kwarteng",
                "outcome": "NEEDS_ATTENTION",
                "summary": "Placement numbers lagged in the first half of the year; mitigations agreed.",
                "start": R("2024-08-01"),
                "end": R("2025-07-31"),
                "outputs": ["31 student placements completed"],
                "score": 3,
                "issues": ["Late confirmation of court capacity", "Attachment supervisors not briefed"],
                "recommendations": ["Confirm capacity by 1 October each year", "Hold a supervisor briefing"],
                "rec": "DEFER",
                "next": R("2026-08-14"),
            },
        ],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Efua Kwarteng", R("2024-01-10")),
            ("STATUS_CHANGED", "Lifecycle status changed to ACTIVE.", "Efua Kwarteng", R("2024-01-15")),
            ("REVIEW_UPDATED", "Value review recorded (ON_TRACK).", "Efua Kwarteng", R("2026-08-21")),
            ("RENEWAL_ALERT_UPDATED", "180-day renewal alert dispatched.", "Nana Asante", R("2026-07-04")),
            ("STATUS_CHANGED", "Lifecycle status changed to RENEWAL_DUE.", "Efua Kwarteng", R("2026-09-01")),
        ],
    },
    {
        "key": "mou-004",
        "stakeholder": "Graphic Communications Group",
        "parties": ["Graphic Communications Group"],
        "reference_no": 9,
        "reference_year": 2024,
        "title": "Media Partnership for Legal Education Awareness",
        "type": "PARTNERSHIP_AGREEMENT",
        "status": "ACTIVE",
        "owner": "Kojo Addo",
        "effective": ago(685),
        "expiry": ahead(45),  # expiring soon and no review on file: exercises renewal + review-overdue states
        "value": "Editorial coverage of CLET announcements and results releases",
        "deliverables": ["Quarterly legal affairs feature", "Results-release press coverage"],
        "legal": "S136-CTR-2024-0110",
        "signed": "S003-DOC-2024-1533",
        "created": ago(700),
        "updated": ago(30),
        "obligations": [
            _ob(
                "Quarterly legal affairs feature",
                "Publish the Q3 feature on the Bar course.",
                "Adwoa Nyarko",
                ago(20),
                "NOT_STARTED",
                lead=7,
                escalation="Registrar",
                progress=[("Feature slot moved to next edition by the desk.", "NOT_STARTED", "Kojo Addo", 26)],
            ),
            _ob(
                "Results-release press coverage",
                "Coverage of the entrance examination results release.",
                "Samuel Tetteh",
                ago(58),
                "COMPLETED",
                ["S003-DOC-2026-0812"],
                7,
                progress=[("Front-page coverage secured.", "COMPLETED", "Kojo Addo", 57)],
            ),
            _ob(
                "Renewal terms discussion",
                "Agree headline terms for renewal with the editor.",
                "Kojo Addo",
                ahead(5),
                "IN_PROGRESS",
                lead=7,
            ),
        ],
        "alerts": [
            _alert(180, "ACKNOWLEDGED", "S074-OUTBOX-7F8E9D0C1B2A", "Nana Asante"),
            _alert(90, "FAILED", None),
            _alert(30, "SCHEDULED"),
        ],
        "reviews": [],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Kojo Addo", ago(700)),
            ("STATUS_CHANGED", "Lifecycle status changed to ACTIVE.", "Kojo Addo", ago(685)),
            ("RENEWAL_ALERT_UPDATED", "180-day renewal alert dispatched.", "Nana Asante", ago(140)),
            ("RENEWAL_ALERT_UPDATED", "180-day renewal alert acknowledged.", "Nana Asante", ago(138)),
            ("RENEWAL_ALERT_UPDATED", "90-day renewal alert failed to send.", "System", ago(45)),
        ],
    },
    {
        "key": "mou-005",
        "stakeholder": "Nigerian Law School",
        "parties": ["Nigerian Law School"],
        "reference_no": 6,
        "reference_year": 2023,
        "title": "Assessment Benchmarking Exchange",
        "type": "MOU",
        "status": "EXPIRED",
        "owner": "Akua Boateng",
        "effective": ago(1100),
        "expiry": ago(40),
        "value": "Peer benchmarking of Bar course assessment models",
        "deliverables": ["Annual benchmarking visit", "Joint assessment moderation report"],
        "legal": "S136-CTR-2023-0058",
        "signed": "S003-DOC-2023-0702",
        "created": ago(1115),
        "updated": ago(40),
        "obligations": [
            _ob(
                "Annual benchmarking visit",
                "Reciprocal visit to compare assessment models.",
                "Akua Boateng",
                ago(192),
                "COMPLETED",
                ["S003-DOC-2026-0301"],
                14,
                progress=[("Visit completed in Abuja.", "COMPLETED", "Akua Boateng", 193)],
            ),
            _ob(
                "Joint moderation report",
                "Publish the joint moderation report.",
                "Akua Boateng",
                ago(90),
                "WAIVED",
                ["S003-DOC-2026-0655"],
                14,
                progress=[("Waived by mutual agreement: partner lacked capacity.", "WAIVED", "Akua Boateng", 88)],
            ),
        ],
        "alerts": [
            _alert(180, "ACKNOWLEDGED", "S074-OUTBOX-0A1B2C3D4E5F", "Akua Boateng"),
            _alert(90, "CANCELLED"),
            _alert(30, "CANCELLED"),
        ],
        "reviews": [
            {
                "date": ago(150),
                "reviewer": "Akua Boateng",
                "outcome": "NO_LONGER_STRATEGIC",
                "summary": "Engagement has lapsed and the partner has not responded to renewal contact.",
                "start": ago(515),
                "end": ago(150),
                "outputs": ["One benchmarking visit completed"],
                "score": 2,
                "issues": ["Partner unresponsive", "Moderation report not delivered"],
                "recommendations": ["Allow the agreement to lapse", "Revisit through the ECOWAS forum"],
                "rec": "TERMINATE",
                "next": ahead(200),
            },
        ],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Akua Boateng", ago(1115)),
            ("STATUS_CHANGED", "Lifecycle status changed to ACTIVE.", "Akua Boateng", ago(1100)),
            ("REVIEW_UPDATED", "Value review recorded (NO_LONGER_STRATEGIC).", "Akua Boateng", ago(150)),
            ("EXPIRED", "Lifecycle status changed to EXPIRED.", "System", ago(40)),
        ],
    },
    {
        "key": "mou-006",
        "stakeholder": "Ford Foundation West Africa",
        "parties": ["Ford Foundation West Africa", "Ghana Bar Association"],
        "reference_no": 3,
        "title": "Access to Justice Programme Funding Framework",
        "type": "COOPERATION_FRAMEWORK",
        "status": "DRAFT",
        "owner": "Akua Boateng",
        "effective": None,
        "expiry": None,
        "value": "Multi-year donor funding for access-to-justice legal education",
        "deliverables": [],
        "legal": None,
        "signed": None,
        "created": ago(12),
        "updated": ago(4),
        "obligations": [],
        "alerts": [],
        "reviews": [],
        "renewals": [],
        "history": [("CREATED", "Partnership draft created.", "Akua Boateng", ago(12))],
    },
    {
        "key": "mou-007",
        "stakeholder": "Embassy of France in Ghana",
        "parties": ["Embassy of France in Ghana"],
        "reference_no": 4,
        "title": "Francophone Legal Education Exchange",
        "type": "MOU",
        "status": "SIGNATURE_PENDING",
        "owner": "Akua Boateng",
        "effective": ahead(21),
        "expiry": ahead(21 + 730),
        "value": "Staff and student exchange with francophone legal institutions",
        "deliverables": ["Annual exchange cohort", "Bilingual legal glossary"],
        "legal": "S136-CTR-2026-0102",
        "signed": None,
        "created": ago(50),
        "updated": ago(6),
        "obligations": [
            _ob(
                "Select first exchange cohort",
                "Agree selection criteria and shortlist.",
                "Akua Boateng",
                ahead(120),
                "NOT_STARTED",
                lead=21,
            ),
        ],
        "alerts": [],
        "reviews": [],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Akua Boateng", ago(50)),
            ("STATUS_CHANGED", "Lifecycle status changed to LEGAL_REVIEW.", "Akua Boateng", ago(30)),
            ("STATUS_CHANGED", "Lifecycle status changed to SIGNATURE_PENDING.", "Adwoa Sarpong", ago(6)),
        ],
    },
    {
        "key": "mou-008",
        "stakeholder": "Kenya School of Law",
        "parties": ["Kenya School of Law"],
        "reference_no": 11,
        "reference_year": 2024,
        "title": "East Africa Legal Education Exchange",
        "type": "MOU",
        "status": "TERMINATED",
        "owner": "Efua Kwarteng",
        "effective": ago(800),
        "expiry": ahead(60),
        "value": "Reciprocal placements for professional law course students",
        "deliverables": ["Annual reciprocal placements"],
        "legal": "S136-CTR-2024-0071",
        "signed": "S003-DOC-2024-0890",
        "created": ago(820),
        "updated": ago(88),
        "termination": {
            "terminatedAt": ago(88).isoformat(),
            "reason": "Terminated by mutual agreement; both parties are scoping a successor framework.",
            "documentationRef": "S003-DOC-2026-0640",
            "finalArchiveRef": "S003-ARC-2026-0114",
            "approvedBy": "Nana Asante",
        },
        "obligations": [
            _ob(
                "Reciprocal placements 2025",
                "Host two Kenyan students for the 2025 attachment.",
                "Efua Kwarteng",
                ago(300),
                "COMPLETED",
                ["S003-DOC-2025-1204"],
                14,
                "Registrar",
            ),
        ],
        "alerts": [_alert(180, "CANCELLED"), _alert(90, "CANCELLED"), _alert(30, "CANCELLED")],
        "reviews": [],
        "renewals": [],
        "history": [
            ("CREATED", "Partnership record created.", "Efua Kwarteng", ago(820)),
            ("STATUS_CHANGED", "Lifecycle status changed to ACTIVE.", "Efua Kwarteng", ago(800)),
            ("TERMINATED", "Agreement terminated: mutual agreement.", "Nana Asante", ago(88)),
        ],
    },
    {
        "key": "mou-009",
        "stakeholder": "Ghana Bar Association",
        "parties": ["Ghana Bar Association", "University of Ghana School of Law"],
        "reference_no": 8,
        "reference_year": 2023,
        "title": "Bar Course Practitioner Mentorship Scheme",
        "type": "PARTNERSHIP_AGREEMENT",
        "status": "ACTIVE",
        "owner": "Nana Asante",
        "effective": ago(240),  # term after the first renewal
        "expiry": ahead(490),
        "value": "Practising lawyers mentor Bar course students across each cohort",
        "deliverables": ["Mentor roster per cohort", "Mentorship completion report"],
        "legal": "S136-CTR-2025-0209",
        "signed": "S003-DOC-2025-1388",
        "renewal_count": 1,
        "created": ago(1000),
        "updated": ago(19),
        "obligations": [
            _ob(
                "Publish mentor roster for the new cohort",
                "Roster shared with the Bar course office.",
                "Ama Owusu",
                ahead(3),
                "IN_PROGRESS",
                lead=7,
                progress=[("Eleven of fifteen mentors confirmed.", "IN_PROGRESS", "Ama Owusu", 3)],
            ),
            _ob(
                "Mentorship completion report",
                "Report for the last completed cohort.",
                "Kofi Mensah",
                ago(45),
                "COMPLETED",
                ["S003-DOC-2026-0744"],
                14,
            ),
            _ob(
                "Mentor safeguarding briefing",
                "Annual safeguarding briefing for all mentors.",
                "Ama Owusu",
                ago(3),
                "NOT_STARTED",
                lead=7,
                escalation="Registrar",
            ),
        ],
        "alerts": [_alert(180, "SCHEDULED"), _alert(90, "SCHEDULED"), _alert(30, "SCHEDULED")],
        "reviews": [
            {
                "date": ago(60),
                "reviewer": "Nana Asante",
                "outcome": "EXCEEDS_EXPECTATIONS",
                "summary": "Mentor participation grew by a third and student feedback was excellent.",
                "start": ago(425),
                "end": ago(60),
                "outputs": ["62 mentors engaged", "Student satisfaction of 94 percent"],
                "score": 5,
                "issues": [],
                "recommendations": ["Extend the scheme to the Legal Practice Course"],
                "rec": "RENEW",
                "next": ago(2),
            },
        ],
        "renewals": [
            {
                "prev_effective": ago(970),
                "prev_expiry": ago(240),
                "legal": "S136-CTR-2025-0209",
                "signed": "S003-DOC-2025-1388",
                "prev_legal": "S136-CTR-2023-0033",
                "prev_signed": "S003-DOC-2023-0511",
                "terms": "Two-year renewal with an expanded mentor roster and annual safeguarding briefing.",
                "by": "Nana Asante",
                "at": ago(245),
            },
        ],
        "history": [
            ("CREATED", "Partnership record created.", "Nana Asante", ago(1000)),
            ("STATUS_CHANGED", "Lifecycle status changed to ACTIVE.", "Nana Asante", ago(970)),
            ("RENEWED", "Agreement renewed for a new term.", "Nana Asante", ago(245)),
            ("REVIEW_UPDATED", "Value review recorded (EXCEEDS_EXPECTATIONS).", "Nana Asante", ago(60)),
        ],
    },
]


async def _by_name(session, name: str) -> Stakeholder | None:
    return await session.scalar(select(Stakeholder).where(Stakeholder.name == name))


async def _seed_stakeholders(session) -> dict[str, Stakeholder]:
    by_name: dict[str, Stakeholder] = {}
    for data in STAKEHOLDERS:
        stakeholder = await _by_name(session, data["name"])
        fields = {k: v for k, v in data.items() if k not in ("contacts", "engagements")}
        created_by = "demo-seed"
        if stakeholder is None:
            stakeholder = Stakeholder(created_by=created_by, **fields)
            session.add(stakeholder)
        else:  # shell created by seed_demo: bring it up to the full mock record
            for key, value in fields.items():
                setattr(stakeholder, key, value)
        await session.flush()
        for contact in data["contacts"]:
            session.add(StakeholderContact(stakeholder_id=stakeholder.id, **contact))
        for engagement in data["engagements"]:
            session.add(StakeholderEngagement(stakeholder_id=stakeholder.id, logged_by="demo-seed", **engagement))
        by_name[stakeholder.name] = stakeholder
    await session.flush()
    return by_name


async def _seed_agreements(session, people: dict[str, Stakeholder]) -> None:
    for data in AGREEMENTS:
        parties = [str(people[name].id) for name in data["parties"]]
        year = data.get("reference_year", TODAY.year)
        agreement = PartnershipAgreement(
            stakeholder_id=people[data["stakeholder"]].id,
            party_stakeholder_ids=parties,
            reference=f"CLET/MOU/{year}/{data['reference_no']:03d}",
            title=data["title"],
            agreement_type=data["type"],
            status=data["status"],
            owner=data["owner"],
            effective_date=data["effective"],
            expiry_date=data["expiry"],
            value_commitment=data["value"],
            deliverables=data["deliverables"],
            legal_contract_ref=data["legal"],
            signed_document_ref=data["signed"],
            renewal_count=data.get("renewal_count", 0),
            termination=data.get("termination"),
            version=1,
            created_at=stamp(data["created"], 10),
            updated_at=stamp(data["updated"], 14, 30),
        )
        session.add(agreement)
        await session.flush()
        aid = agreement.id

        for item in data["obligations"]:
            obligation = PartnershipObligation(
                agreement_id=aid,
                title=item["title"],
                description=item["description"],
                owner=item["owner"],
                due_date=item["due"],
                status=item["status"],
                evidence_references=item["evidence"],
                reminder_lead_days=item["lead"],
                escalation_owner=item["escalation"],
                updated_at=stamp(min(item["due"], TODAY), 9),
            )
            session.add(obligation)
            await session.flush()
            for note, status, actor, days_ago in item["progress"]:
                session.add(
                    ObligationProgressNote(
                        obligation_id=obligation.id,
                        note=note,
                        status=status,
                        actor=actor,
                        created_at=stamp(ago(days_ago), 15),
                    )
                )

        expiry = data["expiry"]
        for item in data["alerts"]:
            scheduled = expiry - dt.timedelta(days=item["milestone"]) if expiry else TODAY
            sent = stamp(min(scheduled, TODAY), 8) if item["status"] in ("SENT", "ACKNOWLEDGED") else None
            session.add(
                PartnershipRenewalAlert(
                    agreement_id=aid,
                    milestone_days=item["milestone"],
                    scheduled_for=scheduled,
                    recipients=RECIPIENTS,
                    status=item["status"],
                    communication_ref=item["ref"],
                    sent_at=sent,
                    acknowledged_at=(sent + dt.timedelta(days=2)) if item["status"] == "ACKNOWLEDGED" and sent else None,
                    acknowledged_by=item["ack_by"],
                )
            )

        for review in data["reviews"]:
            session.add(
                PartnershipReview(
                    agreement_id=aid,
                    review_date=review["date"],
                    reviewer=review["reviewer"],
                    outcome=review["outcome"],
                    summary=review["summary"],
                    period_start=review["start"],
                    period_end=review["end"],
                    outputs=review["outputs"],
                    strategic_score=review["score"],
                    issues=review["issues"],
                    recommendations=review["recommendations"],
                    renewal_recommendation=review["rec"],
                    next_review_date=review["next"],
                )
            )

        for renewal in data["renewals"]:
            session.add(
                PartnershipRenewal(
                    agreement_id=aid,
                    previous_effective_date=renewal["prev_effective"],
                    previous_expiry_date=renewal["prev_expiry"],
                    previous_legal_contract_ref=renewal["prev_legal"],
                    previous_signed_document_ref=renewal["prev_signed"],
                    effective_date=data["effective"],
                    expiry_date=data["expiry"],
                    legal_contract_ref=renewal["legal"],
                    signed_document_ref=renewal["signed"],
                    terms_summary=renewal["terms"],
                    renewed_by=renewal["by"],
                    renewed_at=stamp(renewal["at"], 11),
                )
            )

        for action, summary, actor, day in data["history"]:
            session.add(
                PartnershipHistory(
                    agreement_id=aid,
                    action=action,
                    summary=summary,
                    actor=actor,
                    occurred_at=stamp(day, 10, 15),
                )
            )
        await session.flush()


async def seed(session) -> None:
    if await session.scalar(select(Segment).where(Segment.name == MARKER_SEGMENT)):
        return
    people = await _seed_stakeholders(session)
    for data in SEGMENTS:
        session.add(
            Segment(
                name=data["name"],
                description=data["description"],
                criteria=data["criteria"],
                used_by=data["used_by"],
                created_at=stamp(R(data["updated"]) or TODAY, 9),
                updated_at=stamp(R(data["updated"]) or TODAY, 9),
            )
        )
    await session.flush()
    await _seed_agreements(session, people)
