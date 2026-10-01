"""S091 demo microsites, ported from the donor-microsites mock seed.

Demo access codes for restricted sites (share with UAT testers):

    scholarship-fund-impact-2026        PASSWORD         donor-2026
    board-briefing-clinical-expansion   NAMED_AUDIENCE   board-briefing-2026   (not yet published)
    partners-preview-2027               NAMED_AUDIENCE   partners-2027
    (named-audience sites also unlock with an invited stakeholder's ID as a personal code)

Statuses covered: PUBLISHED (public + restricted), IN_REVIEW, CHANGES_REQUESTED, DRAFT,
APPROVED (never published, and previously published then unpublished), ARCHIVED.
All dates are relative to today. Idempotent: skipped when the annual-report marker exists.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.core.security import hash_password
from app.models.microsites import Microsite, MicrositeReview
from app.models.stakeholders import Stakeholder
from app.models.users import User

MARKER_SLUG = "2026-annual-report"


def _ago(days: int = 0, hours: int = 0) -> dt.datetime:
    now = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    return now - dt.timedelta(days=days, hours=hours)


_n = 0


def _block(type_: str, **fields) -> dict:
    global _n
    _n += 1
    block = {
        "id": f"blk-seed-{_n:03d}",
        "type": type_,
        "heading": "",
        "body": "",
        "assetRefs": [],
        "metrics": [],
        "allocations": [],
        "currency": "GHS",
        "links": [],
        "attribution": "",
    }
    block.update(fields)
    return block


def _m(label: str, value: str, ref: str) -> dict:
    return {"label": label, "value": value, "sourceRef": ref}


def _a(label: str, amount: int) -> dict:
    return {"label": label, "amount": amount}


def _l(label: str, url: str) -> dict:
    return {"label": label, "url": url}


def _annual() -> list[dict]:
    return [
        _block("HERO", heading="2026 Annual Report",
               body="A year of wider access, stronger clinical training and record numbers called to the Bar.",
               assetRefs=["S080-AST-2026-0141"]),
        _block("RICH_TEXT", heading="From the Director of Legal Education",
               body="This year the Council for Legal Education and Training welcomed its largest professional law cohort, opened a second clinical legal education centre and extended bursaries to students in all sixteen regions.\n\nEvery figure on this page is drawn from the Council's reporting system, and every cedi entrusted to us is accounted for below. Thank you to the partners, alumni and donors who made it possible."),
        _block("METRICS", heading="The year at a glance",
               body="Academic year 2025/26. Figures from the S225 reporting warehouse and S150 examinations records.",
               metrics=[
                   _m("Students in professional law training", "3,412", "S225:gsl-enrolment-2026"),
                   _m("New lawyers called to the Bar", "1,086", "S225:bar-call-2025"),
                   _m("Bar examination pass rate", "68%", "S150:bar-exam-pass-rate-2026"),
                   _m("Students on bursaries", "412", "S225:bursary-recipients-2026"),
               ]),
        _block("FUND_UTILISATION", heading="How partner and donor funds were used",
               body="Restricted and unrestricted gifts received in the 2025/26 financial year.",
               allocations=[
                   _a("Scholarships and bursaries", 4_200_000), _a("Campus infrastructure", 2_600_000),
                   _a("Library and e-resources", 1_850_000), _a("Clinical legal education", 1_300_000),
                   _a("Faculty development", 950_000), _a("Programme administration", 700_000),
               ]),
        _block("STORY", heading="Justice closer to home in Kumasi",
               body="The new Legal Aid clinic run with the Kumasi campus gave 220 final-year students supervised practice, and resolved over 600 tenancy, family and employment matters for residents who could not afford a lawyer.",
               assetRefs=["S080-AST-2026-0167"]),
        _block("STORY", heading="The first in her family to be called",
               body="Abena grew up in Tamale and studied on a CLET bursary. In October she was called to the Bar and has joined the Legal Aid Commission in the Northern Region.",
               assetRefs=["S080-AST-2026-0211"]),
        _block("QUOTE",
               body="The bursary did more than pay my fees. It told me that someone believed a girl from Tamale belonged in this profession.",
               attribution="Abena M., called to the Bar, October 2025"),
        _block("GALLERY", heading="Moments from the year",
               assetRefs=["S080-AST-2026-0141", "S080-AST-2026-0152", "S080-AST-2026-0188",
                          "S080-AST-2026-0192", "S080-AST-2026-0173", "S080-AST-2026-0226"]),
        _block("DOWNLOADS", heading="Reports and statements", body="Full documents are held in the S003 records archive.",
               links=[_l("Annual Report 2026 (PDF, 6.2 MB)", "https://clet.gov.gh/reports/annual-report-2026.pdf"),
                      _l("Audited financial statements 2025/26", "https://clet.gov.gh/reports/financial-statements-2026.pdf"),
                      _l("Bar examination statistics", "https://clet.gov.gh/reports/bar-exam-statistics-2026.pdf")]),
        _block("CALL_TO_ACTION", heading="Partner with us in 2027",
               body="Fund a bursary, sponsor a clinic or endow a library collection. Our partnerships team will show you exactly where your gift goes.",
               links=[_l("Talk to the partnerships team", "mailto:partnerships@clet.gov.gh"),
                      _l("Read the donor impact report", "/sites/scholarship-fund-impact-2026")]),
    ]


def _scholarship() -> list[dict]:
    return [
        _block("HERO", heading="Your gift, their future",
               body="How the Legal Access Scholarship Fund opened the profession to 240 students this year.",
               assetRefs=["S080-AST-2026-0173"]),
        _block("METRICS", heading="Student outcomes", metrics=[
            _m("Scholars supported", "240", "S225:lasf-scholars-2026"),
            _m("Completed the year", "94%", "S150:lasf-completion-2026"),
            _m("Women scholars", "58%", "S225:lasf-gender-2026"),
            _m("Regions represented", "16", "S225:lasf-regions-2026"),
        ]),
        _block("FUND_UTILISATION", heading="Fund utilisation",
               body="GHS 3.1 million received from 38 donors; 97% applied directly to students.",
               allocations=[_a("Tuition and examination fees", 1_980_000),
                            _a("Accommodation and living stipends", 720_000), _a("Books and laptops", 310_000),
                            _a("Mentoring and placement", 0), _a("Fund administration", 93_000)]),
        _block("STORY", heading="Kwesi's pupillage in Ho",
               body="Kwesi is the first lawyer from his village in the Volta Region. His scholarship covered his fees and a laptop; he now serves his pupillage with a chambers in Ho that takes legal aid briefs.",
               assetRefs=["S080-AST-2026-0219"]),
        _block("QUOTE", body="We give because we have seen what one qualified lawyer can do for a whole district.",
               attribution="Chair of Trustees, Legal Access Scholarship Fund"),
        _block("DOWNLOADS", heading="For trustees", links=[
            _l("Scholar outcomes dataset (CSV)", "https://clet.gov.gh/donors/lasf-outcomes-2026.csv"),
            _l("Fund statement 2025/26 (PDF)", "https://clet.gov.gh/donors/lasf-statement-2026.pdf")]),
    ]


def _lectures() -> list[dict]:
    return [
        _block("HERO", heading="Access to Justice Lecture Series",
               body="Four evenings with judges, practitioners and scholars on legal aid, technology and the future of legal education.",
               assetRefs=["S080-AST-2026-0226"]),
        _block("RICH_TEXT", heading="Why this series",
               body="Two in three Ghanaians who need legal help never see a lawyer. The series asks what legal education can do about it, and publishes every lecture here."),
        _block("QUOTE", body="A law school is measured not only by the lawyers it produces, but by the people those lawyers serve.",
               attribution="Keynote, opening lecture"),
        _block("DOWNLOADS", heading="Lecture papers",
               links=[_l("Opening lecture paper (PDF)", "https://clet.gov.gh/lectures/a2j-2026-opening.pdf")]),
    ]


def _board() -> list[dict]:
    return [
        _block("HERO", heading="Clinical legal education: results and next steps",
               body="For members of the Council and invited funders."),
        _block("METRICS", heading="Programme results 2025/26", metrics=[
            _m("Students in supervised practice", "220", "S225:cle-students-2026"),
            _m("Community matters resolved", "614", "S225:cle-matters-2026")]),
        _block("FUND_UTILISATION", heading="Proposed budget for three new clinics",
               allocations=[_a("Clinic fit-out (Tamale, Ho, Takoradi)", 1_450_000),
                            _a("Supervising lawyers, two years", 1_120_000), _a("Case management system", 260_000)]),
    ]


def _library() -> list[dict]:
    return [
        _block("HERO", heading="Build the Kumasi Law Library",
               body="Our Kumasi students share 40 reading seats between 1,200 of them. Help us change that.",
               assetRefs=["S080-AST-2026-0204"]),
        _block("RICH_TEXT", heading="The case for a new library"),
        _block("METRICS", heading="Progress towards GHS 12 million"),
        _block("STORY"),
        _block("CALL_TO_ACTION", heading="Pledge a reading seat",
               body="GHS 10,000 names a seat for a generation of law students.",
               links=[_l("Pledge now", "mailto:giving@clet.gov.gh")]),
    ]


def _summit() -> list[dict]:
    return [
        _block("HERO", heading="Legal Education Summit 2025", body="Accra, 12-14 November 2025.",
               assetRefs=["S080-AST-2025-0918"]),
        _block("RICH_TEXT", heading="Programme",
               body="Day one: reforming the professional law course. Day two: clinical and practical training. Day three: regional cooperation."),
        _block("GALLERY", heading="Summit photos", assetRefs=["S080-AST-2025-0918", "S080-AST-2025-0921"]),
        _block("DOWNLOADS", heading="Summit papers",
               links=[_l("Summit communique (PDF)", "https://clet.gov.gh/summit-2025/communique.pdf")]),
    ]


def _partners_preview() -> list[dict]:
    return [
        _block("HERO", heading="Partners' preview: 2027 priorities",
               body="A first look at the programmes we plan to fund next year, for our closest partners.",
               assetRefs=["S080-AST-2026-0188"]),
        _block("METRICS", heading="Where we are heading", metrics=[
            _m("Planned new clinics", "3", "S225:cle-plan-2027"),
            _m("Bursaries targeted", "600", "S225:bursary-target-2027")]),
        _block("FUND_UTILISATION", heading="Indicative 2027 budget",
               allocations=[_a("Bursaries", 5_000_000), _a("Clinics", 2_830_000), _a("Library", 2_000_000)]),
        _block("CALL_TO_ACTION", heading="Shape the plan", body="Tell us where your priorities align.",
               links=[_l("Contact partnerships", "mailto:partnerships@clet.gov.gh")]),
    ]


def _open_day() -> list[dict]:
    return [
        _block("HERO", heading="Law School Open Day 2026",
               body="Meet faculty, tour the campuses and talk to current students.", assetRefs=["S080-AST-2026-0152"]),
        _block("RICH_TEXT", heading="Programme",
               body="Campus tours from 9am, admissions clinic at 11am, moot court demonstration at 2pm."),
        _block("DOWNLOADS", heading="Prospectus",
               links=[_l("Prospectus 2026/27 (PDF)", "https://clet.gov.gh/open-day/prospectus.pdf")]),
        _block("CALL_TO_ACTION", heading="Register your place",
               links=[_l("Register", "mailto:admissions@clet.gov.gh")]),
    ]


def _matching_gift() -> list[dict]:
    return [
        _block("HERO", heading="Double your gift: matching-gift appeal",
               body="Every cedi given before year end is matched by our founding partners.",
               assetRefs=["S080-AST-2026-0192"]),
        _block("RICH_TEXT", heading="How matching works",
               body="Partners have pledged up to GHS 2 million. Your donation to the Legal Access Scholarship Fund is matched one-for-one until the pool is used."),
        _block("METRICS", heading="Appeal progress", metrics=[
            _m("Matched so far", "GHS 1.1m", "S225:matching-gift-2026"),
            _m("Donors", "146", "S225:matching-donors-2026")]),
        _block("CALL_TO_ACTION", heading="Give now", links=[_l("Donate", "mailto:giving@clet.gov.gh")]),
    ]


async def seed(session) -> None:
    if await session.scalar(select(Microsite).where(Microsite.slug == MARKER_SLUG)):
        return

    users = {u.email: u for u in (await session.scalars(select(User))).all()}
    content, rmf = users.get("content@clet.gov.gh"), users.get("rmf@clet.gov.gh")
    author = content.name if content else "Efua Addo"
    author2 = "Nana Asante"
    reviewer = rmf.name if rmf else "Kwame Ofori"
    author_id = str(content.id) if content else ""
    reviewer_id = str(rmf.id) if rmf else ""

    # Named-audience sites need real S081 stakeholder IDs; prefer donors.
    stakeholders = (
        await session.scalars(select(Stakeholder).order_by(Stakeholder.category != "Donor", Stakeholder.name))
    ).all()
    audience = [str(s.id) for s in stakeholders[:2]]
    named_access = "NAMED_AUDIENCE" if audience else "PASSWORD"

    def site(slug, title, tagline, purpose, tpl, status, blocks, *, access="PUBLIC", code=None, audience_ids=None,
             accent="", owner=None, version=1, created=(0,), updated=(0,), published=None, published_version=None,
             archived=None, archive_ref=None, stats=None, last_viewed=None, submitted_by=None):
        views, uniq, avg, downloads = stats or (0, 0, 0, 0)
        return Microsite(
            slug=slug, title=title, tagline=tagline, purpose=purpose, template_id=tpl, status=status,
            access=access, access_code_hash=hash_password(code) if code else None,
            audience_stakeholder_ids=audience_ids if access == "NAMED_AUDIENCE" else [],
            accent_color=accent, owner=owner or author,
            blocks=blocks, version=version, submitted_by=submitted_by,
            published_version=published_version,
            published_blocks=list(blocks) if published_version else None,
            published_title=title if published_version else None,
            published_tagline=tagline if published_version else None,
            published_at=_ago(*published) if published else None,
            archived_at=_ago(*archived) if archived else None, archive_ref=archive_ref,
            views=views, unique_visitors=uniq, total_seconds=avg * views, downloads=downloads,
            last_viewed_at=_ago(*last_viewed) if last_viewed else None,
            created_at=_ago(*created), updated_at=_ago(*updated),
        )

    sites = [
        site(MARKER_SLUG, "2026 Annual Report",
             "Training Ghana's next generation of lawyers: our year in figures and stories.",
             "ANNUAL_REPORT", "tpl-annual-report", "PUBLISHED", _annual(), version=4, published_version=4,
             created=(119,), updated=(46,), published=(46,), stats=(4812, 3127, 184, 642), last_viewed=(0, 3)),
        site("scholarship-fund-impact-2026", "Legal Access Scholarship Fund - Impact 2025/26",
             "A private report for the Fund's donors and trustees.", "DONOR_IMPACT", "tpl-donor-impact", "PUBLISHED",
             _scholarship(), access="PASSWORD", code="donor-2026", accent="#0F766E", version=3, published_version=3,
             created=(81,), updated=(27,), published=(27,), stats=(318, 96, 263, 71), last_viewed=(1, 12)),
        site("access-to-justice-lectures-2026", "Access to Justice Lecture Series 2026",
             "Ideas for a legal profession that serves every Ghanaian.", "THOUGHT_LEADERSHIP",
             "tpl-thought-leadership", "IN_REVIEW", _lectures(), accent="#7C2D12", owner=author2, version=2,
             created=(21,), updated=(7,), submitted_by=author_id),
        site("board-briefing-clinical-expansion", "Board briefing: clinical legal education expansion",
             "Programme results and the case for three new regional clinics.", "DONOR_IMPACT", "tpl-donor-impact",
             "CHANGES_REQUESTED", _board(), access=named_access, code="board-briefing-2026", audience_ids=audience,
             owner="Yaw Darko", version=2, created=(28,), updated=(10,), submitted_by=author_id),
        site("build-the-kumasi-law-library", "Build the Kumasi Law Library",
             "GHS 12 million to give 1,200 students a library worthy of the profession.", "CAMPAIGN", "tpl-campaign",
             "DRAFT", _library(), accent="#B45309", version=1, created=(6,), updated=(6,)),
        site("legal-education-summit-2025", "Legal Education Summit 2025",
             "Three days on the future of legal training in West Africa.", "EVENT_HUB", "tpl-event-hub", "ARCHIVED",
             _summit(), accent="#1E3A8A", owner="Yaw Darko", version=3, published_version=3,
             created=(400,), updated=(256,), published=(363,), archived=(256,), archive_ref="S003/ARC/2026/0412",
             stats=(2210, 1544, 97, 388), last_viewed=(257,)),
        # Beyond the mock seed: cover the remaining states.
        site("partners-preview-2027", "Partners' preview: 2027 priorities",
             "A first look at next year's programmes, for our closest partners.", "DONOR_IMPACT", "tpl-donor-impact",
             "PUBLISHED", _partners_preview(), access=named_access, code="partners-2027", audience_ids=audience,
             accent="#1E40AF", version=2, published_version=2, created=(30,), updated=(5,),
             published=(5,), stats=(42, 9, 205, 11), last_viewed=(0, 20)),
        site("law-school-open-day-2026", "Law School Open Day 2026",
             "Meet faculty, tour the campuses and talk to current students.", "EVENT_HUB", "tpl-event-hub",
             "PUBLISHED", _open_day(), accent="#166534", owner=author2, version=2, published_version=2,
             created=(50,), updated=(14,), published=(14,), stats=(1284, 960, 121, 233), last_viewed=(0, 6)),
        site("matching-gift-appeal-2026", "Double your gift: matching-gift appeal",
             "Every cedi given before year end is matched by our founding partners.", "CAMPAIGN", "tpl-campaign",
             "APPROVED", _matching_gift(), accent="#9D174D", version=2, created=(12,), updated=(2,),
             submitted_by=author_id),
        site("alumni-giving-day-2025", "Alumni Giving Day 2025",
             "One day, every alumnus: the 2025 appeal (withdrawn from public view).", "CAMPAIGN", "tpl-campaign",
             "APPROVED", _matching_gift(), accent="#6D28D9", owner=author2, version=3, published_version=2,
             created=(300,), updated=(90,), published=(280,), stats=(956, 611, 88, 40), last_viewed=(91,),
             submitted_by=author_id),
    ]
    session.add_all(sites)
    await session.flush()
    by_slug = {s.slug: s for s in sites}

    def review(slug, version, decision, comment, actor, actor_id, when):
        session.add(MicrositeReview(microsite_id=by_slug[slug].id, version=version, decision=decision,
                                    comment=comment, actor=actor, actor_id=actor_id, occurred_at=_ago(*when)))

    s, a, c = "SUBMITTED", "APPROVED", "CHANGES_REQUESTED"
    review(MARKER_SLUG, 4, s, "Final figures reconciled with S225 after the audit.", author, author_id, (49, 6))
    review(MARKER_SLUG, 4, a, "Figures and fund utilisation match the audited statements.", reviewer, reviewer_id, (47, 22))
    review("scholarship-fund-impact-2026", 3, s, "", author, author_id, (31,))
    review("scholarship-fund-impact-2026", 3, a, "Approved for the donor group; keep it password-protected.",
           reviewer, reviewer_id, (28, 4))
    review("access-to-justice-lectures-2026", 2, s, "Ready for RMF review ahead of the first lecture.",
           author2, author_id, (7,))
    review("board-briefing-clinical-expansion", 2, s, "", "Yaw Darko", author_id, (12,))
    review("board-briefing-clinical-expansion", 2, c,
           "Add the student outcome stories and cite the S225 source for the budget lines before this goes to the Board.",
           reviewer, reviewer_id, (10,))
    review("legal-education-summit-2025", 3, s, "", "Yaw Darko", author_id, (368,))
    review("legal-education-summit-2025", 3, a, "", reviewer, reviewer_id, (365,))
    review("partners-preview-2027", 2, s, "", author, author_id, (7,))
    review("partners-preview-2027", 2, a, "Audience list confirmed with Partnerships.", reviewer, reviewer_id, (6,))
    review("law-school-open-day-2026", 2, s, "", author2, author_id, (17,))
    review("law-school-open-day-2026", 2, c, "Add the prospectus download.", reviewer, reviewer_id, (16,))
    review("law-school-open-day-2026", 2, s, "Prospectus added.", author2, author_id, (15,))
    review("law-school-open-day-2026", 2, a, "", reviewer, reviewer_id, (14, 3))
    review("matching-gift-appeal-2026", 2, s, "", author, author_id, (3,))
    review("matching-gift-appeal-2026", 2, a, "Approved; publish when the partner pledge letter arrives.",
           reviewer, reviewer_id, (2,))
    review("alumni-giving-day-2025", 2, s, "", author2, author_id, (283,))
    review("alumni-giving-day-2025", 2, a, "", reviewer, reviewer_id, (281,))
