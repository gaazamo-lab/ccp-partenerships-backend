"""S088 demo dataset, ported from the consultation-portal mock data (mockData.ts).

Consultations cover every lifecycle state the UI demonstrates (OPEN, SCHEDULED, CLOSED with a
published outcome, DRAFT with a trigger, REVIEW, ARCHIVED), every question type, ~180 responses
(coded and uncoded, anonymous and identity-linked) and invitation batches. Dates are relative to
today. Idempotent via the consultation slug.
"""

from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import select

from app.models.consultations import Consultation, ConsultationInvitation, ConsultationResponse
from app.models.stakeholders import Segment

SEGMENTS = {
    "SEG-UNI": ("Accredited universities — deans and faculty", "Law faculty leadership at accredited universities.", ["University"]),
    "SEG-BAR": ("Ghana Bar Association regional branches", "Branch executives and CPD coordinators.", ["Professional body"]),
    "SEG-EMP": ("Law firm and employer partners", "Firms and organisations hosting pupillage and graduates.", ["Professional body"]),
    "SEG-JUD": ("Judicial Service training contacts", "Judicial Training Institute focal persons.", ["Judiciary"]),
    "SEG-ALU": ("Alumni (S034) — 2020–2025 cohorts", "Called-to-the-Bar alumni with confirmed contact consent.", ["University"]),
    "SEG-STU": ("NLEMS students (S027) — consent confirmed", "Current Ghana School of Law students who opted in to surveys.", ["University"]),
}

ROLES = ["Student", "Educator", "Legal practitioner", "Employer", "Member of the public"]
FACULTIES = ["University of Ghana School of Law", "KNUST Faculty of Law", "UCC Faculty of Law", "GIMPA Law School", "Other"]
PRIORITIES = ["Clinical practice", "Legal technology", "Ethics", "Research and writing", "Alternative dispute resolution"]

COMMENT_POOL = [
    ("More supervised practical work would improve confidence.", ["th-practical"]),
    ("Moot courts should be assessed, not optional.", ["th-practical", "th-assessment"]),
    ("Examination results take too long and give no feedback.", ["th-assessment"]),
    ("Students need access to online law reports and research databases.", ["th-technology"]),
    ("Introduce training on e-filing before the courts go fully digital.", ["th-technology"]),
    ("Fees are a barrier for students from the northern regions.", ["th-access"]),
    ("Admission numbers are too limited for the demand.", ["th-access"]),
    ("Pupillage placements should be coordinated by CLET.", ["th-practical"]),
    ("Drafting of contracts and pleadings needs much more time.", ["th-practical"]),
    ("Ethics should be taught through real case studies.", []),
    ("Regional campuses would help working students.", ["th-access"]),
    ("Legal research skills are weak among new entrants.", []),
]
NAMES = ["Kofi Boateng", "Abena Owusu", "Yaw Darko", "Akosua Frimpong", "Kwame Mensah", "Efua Quansah", "Selorm Agbeko", "Fatima Iddrisu"]


def _weighted(rng: random.Random, entries):
    total = sum(w for _, w in entries)
    roll = rng.random() * total
    for value, weight in entries:
        roll -= weight
        if roll <= 0:
            return value
    return entries[-1][0]


def _at(day: dt.date, hour: int = 8, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=dt.UTC)


def _stamp(rng: random.Random, start: dt.datetime, end: dt.datetime) -> dt.datetime:
    span = max(1, int((end - start).total_seconds()))
    return start + dt.timedelta(seconds=int(rng.random() * span))


def _tr(fr_prompt=None, ar_prompt=None, fr_opts=None, ar_opts=None, desc_fr=None, desc_ar=None):
    out = {}
    for code, prompt, opts, desc in (("fr", fr_prompt, fr_opts, desc_fr), ("ar", ar_prompt, ar_opts, desc_ar)):
        if prompt or opts:
            item = {"prompt": prompt or ""}
            if desc:
                item["description"] = desc
            if opts:
                item["options"] = opts
            out[code] = item
    return out or None


def _q(id, type, prompt, required=False, **extra):
    q = {"id": id, "type": type, "prompt": prompt, "required": required}
    q.update({k: v for k, v in extra.items() if v is not None})
    return q


def _curriculum_questions():
    return [
        _q("sec-about", "SECTION", "About you", description="Tell us which group you belong to.",
           translations=_tr("À propos de vous", "نبذة عنك", desc_fr="Indiquez-nous à quel groupe vous appartenez.", desc_ar="أخبرنا إلى أي فئة تنتمي.")),
        _q("role", "SINGLE_CHOICE", "Which group best describes you?", True, options=ROLES,
           translations=_tr("Quel groupe vous décrit le mieux ?", "أي فئة تصفك بشكل أفضل؟",
                            ["Étudiant", "Enseignant", "Praticien du droit", "Employeur", "Membre du public"],
                            ["طالب", "معلم", "ممارس قانوني", "صاحب عمل", "فرد من الجمهور"])),
        _q("institution", "DROPDOWN", "Which law faculty are you enrolled in?", True, options=FACULTIES,
           visibleIf=[{"questionId": "role", "operator": "EQUALS", "value": "Student"}],
           translations=_tr("Dans quelle faculté de droit êtes-vous inscrit ?", "في أي كلية حقوق أنت مسجل؟",
                            ["Université du Ghana – Faculté de droit", "KNUST – Faculté de droit", "Université de Cape Coast – Faculté de droit", "GIMPA – Faculté de droit", "Autre"],
                            ["جامعة غانا – كلية الحقوق", "جامعة كوامي نكروما – كلية الحقوق", "جامعة كيب كوست – كلية الحقوق", "معهد GIMPA – كلية الحقوق", "أخرى"])),
        _q("sec-curriculum", "SECTION", "Curriculum", translations=_tr("Programme", "المنهج")),
        _q("preparedness", "RATING", "How well does the current curriculum prepare graduates for practice?", True, min=1, max=5,
           minLabel="Not at all prepared", maxLabel="Very well prepared",
           translations=_tr("Dans quelle mesure le programme actuel prépare-t-il les diplômés à la pratique ?", "إلى أي مدى يُعِدّ المنهج الحالي الخريجين للممارسة المهنية؟")),
        _q("priorities", "MULTI_CHOICE", "Which areas should receive greater emphasis?", True, options=PRIORITIES,
           translations=_tr("Quels domaines devraient recevoir davantage d’attention ?", "ما المجالات التي ينبغي التركيز عليها أكثر؟",
                            ["Pratique clinique", "Technologies juridiques", "Déontologie", "Recherche et rédaction", "Modes alternatifs de règlement des différends"],
                            ["الممارسة العيادية", "التكنولوجيا القانونية", "الأخلاقيات المهنية", "البحث والكتابة", "الوسائل البديلة لتسوية النزاعات"])),
        _q("gap", "LONG_TEXT", "What single gap most affects graduate preparedness?", False,
           description="Shown because you rated preparedness below 3.",
           visibleIf=[{"questionId": "preparedness", "operator": "LESS_THAN", "value": 3}],
           translations=_tr("Quelle lacune affecte le plus la préparation des diplômés ?", "ما أبرز فجوة تؤثر في جاهزية الخريجين؟")),
        _q("sec-overall", "SECTION", "Overall", translations=_tr("Dans l’ensemble", "بشكل عام")),
        _q("nps", "NPS", "How likely are you to recommend CLET's legal education programmes to a colleague?", False, min=0, max=10,
           minLabel="Not at all likely", maxLabel="Extremely likely",
           translations=_tr("Quelle est la probabilité que vous recommandiez les programmes de formation juridique du CLET à un collègue ?", "ما مدى احتمال أن توصي زميلاً ببرامج التعليم القانوني التي يقدمها CLET؟")),
        _q("comments", "LONG_TEXT", "What is the most important change CLET should consider?", False,
           translations=_tr("Quel est le changement le plus important que le CLET devrait envisager ?", "ما أهم تغيير ينبغي أن ينظر فيه CLET؟")),
        _q("start-date", "DATE", "When did you start your current programme or role? (optional)", False),
        _q("short-note", "SHORT_TEXT", "Anything else in one line?", False),
    ]


async def _segment_ids(session) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key, (name, description, categories) in SEGMENTS.items():
        segment = await session.scalar(select(Segment).where(Segment.name == name))
        if segment is None:
            segment = Segment(
                name=name,
                description=description,
                criteria={"categories": categories, "statuses": [], "owners": [], "consentedOnly": True},
                used_by=["S088"],
            )
            session.add(segment)
            await session.flush()
        ids[key] = str(segment.id)
    return ids


def _curriculum_responses(consultation_id, opens: dt.datetime, now: dt.datetime) -> list[ConsultationResponse]:
    rng = random.Random(88)
    rows = []
    for index in range(130):
        role = _weighted(rng, [("Student", 38), ("Educator", 14), ("Legal practitioner", 26), ("Employer", 12), ("Member of the public", 10)])
        prep = _weighted(rng, [(1, 8), (2, 22), (3, 34), (4, 26), (5, 10)])
        priorities = [p for p in PRIORITIES if rng.random() < 0.38] or [rng.choice(PRIORITIES)]
        answers: dict = {"role": role, "preparedness": prep, "priorities": priorities}
        if role == "Student":
            answers["institution"] = _weighted(rng, [(FACULTIES[0], 5), (FACULTIES[1], 3), (FACULTIES[2], 2), (FACULTIES[3], 2), ("Other", 1)])
        themes: dict = {}
        if prep < 3 and rng.random() < 0.7:
            text, ids = rng.choice(COMMENT_POOL)
            answers["gap"] = text
            if index % 2 == 0 and ids:
                themes["gap"] = ids
        if rng.random() < 0.8:
            answers["nps"] = min(10, max(0, round(prep * 1.6 + rng.random() * 3)))
        if rng.random() < 0.55:
            text, ids = rng.choice(COMMENT_POOL)
            answers["comments"] = text
            if index % 3 != 0 and ids:
                themes["comments"] = ids
        consent = rng.random() < 0.18
        name = rng.choice(NAMES)
        rows.append(
            ConsultationResponse(
                consultation_id=consultation_id,
                submitted_at=_stamp(rng, opens + dt.timedelta(hours=1), now - dt.timedelta(hours=1)),
                language=_weighted(rng, [("en", 86), ("fr", 9), ("ar", 5)]),
                answers=answers,
                consent_to_identity_link=consent,
                respondent={"name": name, "email": f"{name.lower().replace(' ', '.')}@example.com", "stakeholderGroup": role} if consent else None,
                themes=themes,
            )
        )
    rows.append(
        ConsultationResponse(
            consultation_id=consultation_id,
            submitted_at=now - dt.timedelta(hours=30),
            language="en",
            answers={"role": "Student", "institution": "KNUST Faculty of Law", "preparedness": 3, "priorities": ["Clinical practice", "Legal technology"], "nps": 7,
                     "comments": "More supervised practical work would improve confidence.", "start-date": "2024-09-02", "short-note": "Thank you for asking."},
            consent_to_identity_link=False, respondent=None, themes={"comments": ["th-practical"]},
        )
    )
    rows.append(
        ConsultationResponse(
            consultation_id=consultation_id,
            submitted_at=now - dt.timedelta(hours=26),
            language="en",
            answers={"role": "Employer", "preparedness": 2, "priorities": ["Research and writing", "Ethics"], "gap": "Drafting of opinions and pleadings.", "nps": 5,
                     "comments": "Writing and professional judgement need stronger assessment."},
            consent_to_identity_link=True,
            respondent={"name": "Ama Mensah", "email": "ama@example.com", "stakeholderGroup": "Employer"},
            themes={"comments": ["th-assessment"]},
        )
    )
    return rows


def _literacy_responses(consultation_id, opens: dt.datetime, closes: dt.datetime) -> list[ConsultationResponse]:
    rng = random.Random(303)
    suggestions = [
        ("Explain the law in Twi on local radio.", ["th-language", "th-radio"]),
        ("Short videos in Ewe and Ga would reach more people.", ["th-language"]),
        ("Hold community durbars with lawyers answering questions.", ["th-radio"]),
        ("Avoid legal jargon and give examples.", []),
    ]
    all_topics = ["Land and property", "Family and inheritance", "Employment rights", "Consumer protection", "Criminal procedure"]
    weights = [0.7, 0.6, 0.35, 0.25, 0.2]
    rows = []
    for _ in range(40):
        topics = [t for t, w in zip(all_topics, weights) if rng.random() < w] or ["Land and property"]
        answers: dict = {
            "topics": topics,
            "channel": _weighted(rng, [("Radio", 14), ("Social media", 9), ("Community meetings", 8), ("Printed leaflets", 4), ("Website", 5)]),
            "usefulness": _weighted(rng, [(1, 6), (2, 12), (3, 12), (4, 7), (5, 3)]),
        }
        themes: dict = {}
        if rng.random() < 0.6:
            text, ids = rng.choice(suggestions)
            answers["suggestion"] = text
            if ids:
                themes["suggestion"] = ids
        rows.append(
            ConsultationResponse(
                consultation_id=consultation_id,
                submitted_at=_stamp(rng, opens, closes),
                language="en",
                answers=answers,
                consent_to_identity_link=False,
                respondent=None,
                themes=themes,
            )
        )
    return rows


async def seed(session) -> None:
    if await session.scalar(select(Consultation.id).where(Consultation.slug == "legal-education-curriculum-review-2026")):
        return
    today = dt.date.today()
    now = dt.datetime.now(dt.UTC)
    seg = await _segment_ids(session)
    d = dt.timedelta

    open_start, open_end = _at(today - d(days=28)), _at(today + d(days=19), 23, 59)
    curriculum = Consultation(
        slug="legal-education-curriculum-review-2026",
        title="Legal Education Curriculum Review 2026",
        summary="Help shape the knowledge and practical skills expected from future legal professionals.",
        description="CLET is reviewing the legal education curriculum. We invite students, educators, employers, legal practitioners, and members of the public to share evidence and priorities for reform.",
        category="Legal education",
        status="OPEN",
        languages=["en", "fr", "ar"],
        opens_at=open_start,
        closes_at=open_end,
        estimated_minutes=6,
        anonymous_allowed=True,
        collect_identity=True,
        audience_source="MIXED",
        audience_segment_ids=[seg["SEG-UNI"], seg["SEG-BAR"]],
        invited_count=209,
        questions=_curriculum_questions(),
        triggers=[],
        themes=[
            {"id": "th-practical", "label": "Practical skills", "description": "Clinical work, pupillage, advocacy and drafting practice."},
            {"id": "th-assessment", "label": "Assessment", "description": "Examination format, feedback and marking."},
            {"id": "th-technology", "label": "Legal technology", "description": "Research databases, e-filing and digital practice."},
            {"id": "th-access", "label": "Access and cost", "description": "Fees, admissions capacity and regional access."},
        ],
        approved_by="Esi Ofori (AQAI)",
        created_by="seed",
    )

    pd = Consultation(
        slug="professional-development-priorities-2027",
        title="Professional Development Priorities 2027",
        summary="Tell us which continuing professional development topics matter most for 2027.",
        description="This targeted consultation will inform the 2027 professional development programme for members of the Bar.",
        category="Professional development",
        status="SCHEDULED",
        languages=["en"],
        opens_at=_at(today + d(days=6)),
        closes_at=_at(today + d(days=34), 23, 59),
        estimated_minutes=4,
        anonymous_allowed=False,
        collect_identity=True,
        audience_source="CRM",
        audience_segment_ids=[seg["SEG-BAR"], seg["SEG-EMP"]],
        invited_count=255,
        questions=[
            _q("cpd-topics", "MULTI_CHOICE", "Which CPD topics would you attend in 2027?", True,
               options=["Commercial arbitration", "Data protection (Act 843)", "Courtroom technology", "Practice management", "Legal ethics refresher"]),
            _q("cpd-format", "SINGLE_CHOICE", "Which format suits you best?", True,
               options=["In person (Accra)", "In person (regional)", "Live webinar", "Recorded modules"]),
            _q("cpd-hours", "NUMBER", "How many CPD hours do you expect to complete in 2027?", False, min=0, max=200),
        ],
        triggers=[],
        themes=[],
        approved_by="Kwabena Asante (CDT)",
        created_by="seed",
    )

    lit_open, lit_close = _at(today - d(days=120)), _at(today - d(days=91), 23, 59)
    literacy = Consultation(
        slug="public-legal-literacy-needs",
        title="Public Legal Literacy Needs",
        summary="A completed consultation on priority topics for public legal education.",
        description="This consultation gathered community priorities for accessible legal information.",
        category="Public engagement",
        status="CLOSED",
        languages=["en"],
        opens_at=lit_open,
        closes_at=lit_close,
        estimated_minutes=5,
        anonymous_allowed=True,
        collect_identity=False,
        audience_source="PUBLIC",
        audience_segment_ids=[],
        invited_count=None,
        questions=[
            _q("topics", "MULTI_CHOICE", "Which legal topics would you most like plain-language information on?", True,
               options=["Land and property", "Family and inheritance", "Employment rights", "Consumer protection", "Criminal procedure"]),
            _q("channel", "SINGLE_CHOICE", "How do you prefer to receive legal information?", True,
               options=["Radio", "Social media", "Community meetings", "Printed leaflets", "Website"]),
            _q("usefulness", "RATING", "How useful is the legal information currently available to you?", True, min=1, max=5, minLabel="Not useful", maxLabel="Very useful"),
            _q("suggestion", "LONG_TEXT", "What would make legal information easier to understand?", False),
        ],
        triggers=[],
        themes=[
            {"id": "th-language", "label": "Local languages", "description": "Requests for Twi, Ewe, Ga, Dagbani and other languages."},
            {"id": "th-radio", "label": "Radio and community", "description": "Radio programmes and community forums."},
        ],
        outcome_summary=(
            "Thank you to the 40 people who took part. Land and property and family and inheritance were the most requested topics, and radio and community meetings were the preferred channels — particularly outside Greater Accra.\n\n"
            "Many of you asked for information in local languages. In response, CLET will pilot a series of plain-language radio segments in Twi and Ewe from January 2027, publish summary leaflets on land registration and inheritance, and review the public legal information pages on the CLET website with community organisations."
        ),
        approved_by="Esi Ofori (AQAI)",
        created_by="seed",
    )

    conference = Consultation(
        slug="annual-legal-education-conference-feedback-2026",
        title="Annual Legal Education Conference 2026 — Feedback",
        summary="Tell us how the 2026 conference went and what to change next year.",
        description="Sent automatically to confirmed attendees the day after the conference (S078 event).",
        category="Event feedback",
        status="DRAFT",
        languages=["en"],
        opens_at=_at(today + d(days=45)),
        closes_at=_at(today + d(days=59), 23, 59),
        estimated_minutes=3,
        anonymous_allowed=True,
        collect_identity=True,
        audience_source="CRM",
        audience_segment_ids=[seg["SEG-UNI"], seg["SEG-JUD"]],
        invited_count=0,
        questions=[
            _q("overall", "RATING", "Overall, how would you rate the conference?", True, min=1, max=5, minLabel="Poor", maxLabel="Excellent"),
            _q("sessions", "LONG_TEXT", "Which session was most valuable, and why?", False),
        ],
        triggers=[{"id": "TRG-001", "type": "POST_EVENT", "sourceRef": "S078-EVT-2026-014", "delayDays": 1, "active": True}],
        themes=[],
        created_by="seed",
    )

    accreditation = Consultation(
        slug="accreditation-standards-law-faculties",
        title="Accreditation Standards for Law Faculties — Consultation Draft",
        summary="Comment on proposed minimum standards for accredited law faculties.",
        description="AQAI is consulting on revised minimum standards for staffing, libraries and clinical legal education at accredited law faculties.",
        category="Accreditation",
        status="REVIEW",
        languages=["en", "fr"],
        opens_at=_at(today + d(days=13)),
        closes_at=_at(today + d(days=73), 23, 59),
        estimated_minutes=10,
        anonymous_allowed=True,
        collect_identity=True,
        audience_source="MIXED",
        audience_segment_ids=[seg["SEG-UNI"], seg["SEG-ALU"]],
        invited_count=0,
        questions=[
            _q("support", "SINGLE_CHOICE", "Do you support the proposed staffing ratio of one full-time lecturer per 25 students?", True,
               options=["Support", "Support with changes", "Oppose", "No view"],
               translations=_tr("Soutenez-vous le ratio proposé d’un enseignant à temps plein pour 25 étudiants ?", fr_opts=["Je soutiens", "Je soutiens avec modifications", "Je m’oppose", "Sans avis"])),
            _q("changes", "LONG_TEXT", "What changes would you make?", True,
               visibleIf=[{"questionId": "support", "operator": "EQUALS", "value": "Support with changes"}],
               translations=_tr("Quelles modifications proposeriez-vous ?")),
            _q("clinic-hours", "NUMBER", "Minimum supervised clinical hours you would require per student", False, min=0, max=500),
        ],
        triggers=[{"id": "TRG-002", "type": "CALENDAR", "sourceRef": "Accreditation cycle — Q4 2026", "delayDays": 0, "active": False}],
        themes=[],
        created_by="seed",
    )

    archived = Consultation(
        slug="bar-admissions-process-feedback-2025",
        title="Bar Admissions Process Feedback 2025",
        summary="An archived consultation on the experience of the 2025 Bar admissions process.",
        description="Archived after the outcome was published; retained for the record.",
        category="Admissions",
        status="ARCHIVED",
        languages=["en"],
        opens_at=_at(today - d(days=400)),
        closes_at=_at(today - d(days=370), 23, 59),
        estimated_minutes=3,
        anonymous_allowed=True,
        collect_identity=False,
        audience_source="PUBLIC",
        audience_segment_ids=[],
        invited_count=None,
        questions=[
            _q("experience", "RATING", "How would you rate the admissions process?", True, min=1, max=5),
            _q("improve", "SHORT_TEXT", "One thing to improve?", False),
        ],
        triggers=[],
        themes=[],
        outcome_summary="Thank you for your feedback. Applicants asked for clearer timelines; the Registry now publishes a dated admissions calendar each year.",
        approved_by="Esi Ofori (AQAI)",
        created_by="seed",
    )

    session.add_all([curriculum, pd, literacy, conference, accreditation, archived])
    await session.flush()

    session.add_all(_curriculum_responses(curriculum.id, open_start, now))
    session.add_all(_literacy_responses(literacy.id, lit_open, lit_close))
    session.add_all(
        ConsultationResponse(
            consultation_id=archived.id,
            submitted_at=archived.opens_at + d(days=2 + i),
            language="en",
            answers={"experience": 2 + i % 4, "improve": "Publish the timeline earlier."} if i % 2 else {"experience": 2 + i % 4},
            consent_to_identity_link=False,
            respondent=None,
            themes={},
        )
        for i in range(6)
    )
    session.add_all(
        [
            ConsultationInvitation(
                consultation_id=curriculum.id, kind="INVITATION", segment_ids=[seg["SEG-UNI"], seg["SEG-BAR"]],
                recipient_count=209, excluded_count=29, communication_ref="S074-CON-2026-001-001",
                sent_by="Nana Adjei", sent_at=open_start + d(hours=1),
            ),
            ConsultationInvitation(
                consultation_id=curriculum.id, kind="REMINDER", segment_ids=[seg["SEG-UNI"], seg["SEG-BAR"]],
                recipient_count=131, excluded_count=107, communication_ref="S074-CON-2026-001-002",
                sent_by="Nana Adjei", sent_at=now - d(days=14),
            ),
            ConsultationInvitation(
                consultation_id=pd.id, kind="INVITATION", segment_ids=[seg["SEG-BAR"], seg["SEG-EMP"]],
                recipient_count=255, excluded_count=51, communication_ref="S074-CON-2026-002-001",
                sent_by="Akosua Mensah", sent_at=now - d(days=3),
            ),
        ]
    )
