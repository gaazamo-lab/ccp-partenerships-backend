"""
S084 Visa & Travel Authorisation demo dataset.

Ported from the frontend mock register (`apps/travel-authorisation/src/features/requests/mockData.ts`)
and widened so every workflow state, both directions and the awkward cases (returned, rejected,
cancelled, amended, overdue approval, failed notification, evidence waived by exception, a start
date that has already passed) can be shown from the database.

Everything is dated relative to today, so the register never goes stale. Idempotent: it does nothing
when any travel request already exists. It flushes but never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select, text

from app.models.travel import TravelPolicy, TravelRequest
from app.services import travel as rules

LINE_MANAGER = "Efua Kwarteng"
SENIOR = "Kwabena Asare"
WELFARE = "Adjoa Nyarko"
IR_OFFICER = "Esi Boateng"
RMF = "Kwame Ofori"
DTI = "Dela Tetteh"

RATE_VERSION = "RATE-2026.1"
TEMPLATE = "S084 standard v3.1"

#: (label, assignee) per approval chain. Student travel adds the P&C welfare check, inbound adds IR.
CHAINS: dict[str, list[tuple[str, str]]] = {
    "staff": [("Line manager", LINE_MANAGER), ("Senior approver", SENIOR), ("RMF cost review", RMF)],
    "student": [("Line manager", LINE_MANAGER), ("Student welfare (P&C)", WELFARE), ("Senior approver", SENIOR)],
    "inbound": [("Line manager", LINE_MANAGER), ("Senior approver", SENIOR), ("IR protocol clearance", IR_OFFICER)],
}

EVIDENCE: dict[str, list[tuple[str, bool]]] = {
    "staff": [("Invitation or business case", False), ("Travel itinerary", False), ("Funding confirmation", True)],
    "student": [
        ("Passport bio page", True),
        ("Travel itinerary", False),
        ("Proof of enrolment", True),
        ("Sponsor or funding confirmation", True),
        ("Parent or guardian consent", True),
    ],
    "inbound": [
        ("Passport bio page", True),
        ("Invitation or appointment letter", False),
        ("Travel itinerary", False),
    ],
}

INTEGRATIONS: dict[str, list[tuple[str, str]]] = {
    "inbound": [
        ("S083", "Delegation record"),
        ("GIS", "Clearance liaison"),
        ("S031", "Accommodation"),
        ("S003", "Official records"),
        ("S074", "Official communications"),
    ],
    "outbound": [
        ("S140", "Staff and policy"),
        ("S144", "Estimate and claim handoff"),
        ("S003", "Official records"),
        ("S074", "Official communications"),
    ],
}


def _stamp(now: dt.datetime, days_ago: float, hour: int = 9, minute: int = 0) -> str:
    moment = (now - dt.timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def _parse(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _evidence(kind: str, statuses: list[str], ref_prefix: str, reviewer: str, extra: dict[int, str] | None = None):
    """`statuses` is one of Received / Missing / Exception per checklist line."""
    rows = []
    for index, ((label, sensitive), status) in enumerate(zip(EVIDENCE[kind], statuses, strict=True)):
        item: dict[str, Any] = {
            "id": f"ev-{index + 1}",
            "label": label,
            "required": True,
            "sensitive": sensitive,
            "status": status,
        }
        if status == "Received":
            item["reference"] = f"{ref_prefix}-{index + 1:02d}"
            item["reviewedBy"] = reviewer
        elif status == "Exception":
            item["exceptionReason"] = (extra or {}).get(index, "Waived by the reviewer.")
            item["reviewedBy"] = reviewer
        rows.append(item)
    return rows


def _approvals(kind: str, statuses: list[str], now: dt.datetime, first_days_ago: float, version: int, comments=None):
    rows = []
    for index, ((label, assignee), status) in enumerate(zip(CHAINS[kind], statuses, strict=True)):
        step: dict[str, Any] = {"id": f"ap-{index + 1}", "label": label, "assignee": assignee, "status": status}
        if status in {"Approved", "Returned", "Rejected"}:
            step["decidedAt"] = _stamp(now, max(first_days_ago - index * 0.4, 0), 10 + index, 15 + index * 7)
            step["comment"] = (comments or {}).get(index, "Approved." if status == "Approved" else "See note.")
            step["recordVersion"] = version
        rows.append(step)
    return rows


def _integrations(direction: str, states: dict[str, tuple[str, str | None, str | None]], now: dt.datetime, days_ago: float):
    """`states` maps system -> (status, reference, note); anything absent is Not started."""
    rows = []
    for system, label in INTEGRATIONS[direction]:
        status, reference, note = states.get(system, ("Not started", None, None))
        row: dict[str, Any] = {"system": system, "label": label, "status": status}
        if reference:
            row["reference"] = reference
        if note:
            row["note"] = note
        if status != "Not started":
            row["correlationId"] = f"COR-{system}-{uuid.uuid4().hex[:8].upper()}"
            row["updatedAt"] = _stamp(now, days_ago, 14, 5)
        rows.append(row)
    return rows


def _document(ref: str, inbound: bool, seq: int, signatory: str, now: dt.datetime, days_ago: float, status: str):
    return {
        "id": str(uuid.uuid4()),
        "type": "Support letter" if inbound else "Travel authorisation",
        "reference": f"{ref}-{'SL' if inbound else 'TA'}{seq:02d}",
        "templateVersion": TEMPLATE,
        "signatory": signatory,
        "issuedAt": _stamp(now, days_ago, 11, 30),
        "status": status,
    }


def _notification(ref: str, n: int, subject: str, recipient: str, status: str, now: dt.datetime, days_ago: float):
    return {
        "id": f"ntf-{ref[-4:]}-{n}",
        "subject": subject,
        "recipient": recipient,
        "status": status,
        "correlationId": f"S074-{ref[-9:]}-{n:02d}",
        "sentAt": _stamp(now, days_ago, 12, 10),
    }


def _estimate(days: int, rate: float, transport: float, accommodation: float, other: float = 0):
    return {
        "currency": "GHS",
        "perDiem": float(days) * rate,
        "transport": float(transport),
        "accommodation": float(accommodation),
        "other": float(other),
        "eligibleDays": days,
        "dailyRate": float(rate),
        "rateVersion": RATE_VERSION,
    }


def _specs(today: dt.date, now: dt.datetime) -> list[dict[str, Any]]:
    def d(offset: int) -> dt.date:
        return today + dt.timedelta(days=offset)

    def h(days_ago: float, title: str, detail: str, hour: int = 10, minute: int = 0) -> dict[str, str]:
        return {"title": title, "detail": detail, "at": _stamp(now, days_ago, hour, minute)}

    specs: list[dict[str, Any]] = []

    # 1. Mock 0042 - inbound examiner, mid-approval; the senior authority is the open step.
    specs.append(
        dict(
            direction="Inbound", category="Examiner visa support", traveller="Dr. Amara Okafor",
            nationality="Nigerian", purpose="External examiner appointment", destination="Accra, Ghana",
            host="Ghana School of Law", start=d(13), end=d(19), requester=IR_OFFICER, status="Pending approvals",
            kind="inbound", submitted=8, source_reference="S083-DEL-0194",
            evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-EXM",
            approvals=["Approved", "Pending", "Approved"], first_decision=6,
            estimate=_estimate(6, 350, 4800, 4200),
            integrations={
                "S083": ("Complete", "S083-DEL-0194", None),
                "GIS": ("Pending", "GIS-REQ-8812", "Clearance liaison opened."),
                "S003": ("Pending", None, None),
            },
            history=[
                h(8, "Request raised", f"{IR_OFFICER} created the request.", 15, 6),
                h(8, "Moved to Submitted", f"{IR_OFFICER} advanced the request.", 9, 15),
                h(7, "Moved to Screening", f"{IR_OFFICER} advanced the request.", 9, 40),
                h(7, "Moved to Pending approvals", f"{IR_OFFICER} advanced the request.", 10, 5),
                h(6, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(5, "IR protocol clearance approved", f"{IR_OFFICER}: Approved.", 11, 40),
                h(5, "Estimate saved", f"GHS 11,100.00 at {RATE_VERSION} - {DTI}", 12, 0),
            ],
        )
    )

    # 2. Mock 0041 - outbound staff travel, fully authorised.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Kwame Asante",
            purpose="Regional legal education workshop", destination="Nairobi, Kenya", start=d(4), end=d(9),
            requester="Kwame Asante", status="Travel authorised", kind="staff", submitted=13,
            source_reference="S140-EMP-0088", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-KA",
            approvals=["Approved", "Approved", "Approved"], first_decision=11,
            estimate=_estimate(5, 720, 7200, 5600),
            documents=[("Travel authorisation", 7, "Current")],
            integrations={
                "S140": ("Complete", "S140-EMP-0088", None),
                "S144": ("Complete", "S144-EST-2911", "Estimate handed to finance."),
                "S003": ("Complete", "S003-DOC-6620", "Authorisation filed."),
                "S074": ("Complete", "S074-COM-4410", None),
            },
            notifications=[("Travel authorisation issued", "Kwame Asante", "Delivered", 7)],
            history=[
                h(13, "Request raised", "Kwame Asante created the request.", 15, 6),
                h(13, "Moved to Submitted", "Kwame Asante advanced the request."),
                h(12, "Moved to Screening", f"{DTI} advanced the request."),
                h(12, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(11, "Line manager approved", f"{LINE_MANAGER}: Approved.", 14, 8),
                h(10, "Senior approver approved", f"{SENIOR}: Approved.", 10, 31),
                h(10, "RMF cost review approved", f"{RMF}: Approved.", 16, 2),
                h(7, "Travel authorisation issued", f"S084 travel authorisation signed by {SENIOR}.", 8, 54),
            ],
            signatory=SENIOR,
        )
    )

    # 3. Mock 0039 - inbound exchange student, returned for missing enrolment proof.
    specs.append(
        dict(
            direction="Inbound", category="Exchange student support", traveller="Naledi Molefe",
            nationality="South African", purpose="Academic exchange semester", destination="Accra, Ghana",
            host="CLET Academic Affairs", start=d(103), end=d(243), requester=IR_OFFICER, status="Returned",
            kind="inbound", submitted=17, evidence=["Received", "Missing", "Received"], ref_prefix="S003-DOC-NM",
            approvals=["Returned", "Superseded", "Superseded"], first_decision=9,
            approval_comments={0: "Proof of enrolment is required before this can proceed."},
            history=[
                h(17, "Request raised", f"{IR_OFFICER} created the request.", 9, 10),
                h(17, "Moved to Submitted", f"{IR_OFFICER} advanced the request.", 9, 10),
                h(16, "Moved to Screening", f"{DTI} advanced the request."),
                h(15, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(9, "Line manager returned", f"{LINE_MANAGER}: Proof of enrolment is required before this can proceed.", 13, 22),
            ],
            last_change_reason=None,
        )
    )

    # 4. Mock 0036 - outbound, approved, trip already under way but no authorisation issued yet (overdue).
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Adwoa Frimpong",
            purpose="Quality assurance conference", destination="Kigali, Rwanda", start=d(-4), end=d(0),
            requester="Adwoa Frimpong", status="Approved", kind="staff", submitted=19,
            source_reference="S140-EMP-0142", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-AF",
            approvals=["Approved", "Approved", "Approved"], first_decision=17,
            estimate=_estimate(4, 700, 6500, 3900),
            integrations={"S140": ("Complete", "S140-EMP-0142", None), "S144": ("Pending", None, None), "S003": ("Pending", None, None)},
            history=[
                h(19, "Request raised", "Adwoa Frimpong created the request.", 9, 30),
                h(19, "Moved to Submitted", "Adwoa Frimpong advanced the request."),
                h(18, "Moved to Screening", f"{DTI} advanced the request."),
                h(18, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(17, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 17),
                h(9, "Senior approver approved", f"{SENIOR}: Approved.", 15, 22),
                h(6, "RMF cost review approved", f"{RMF}: Approved.", 9, 8),
            ],
        )
    )

    # 5. Student draft - evidence largely outstanding.
    specs.append(
        dict(
            direction="Outbound", category="Student outbound travel", traveller="Yaw Owusu",
            purpose="Inter-university moot court competition", destination="Arusha, Tanzania", start=d(40), end=d(46),
            requester="Yaw Owusu", status="Draft", kind="student", submitted=None,
            evidence=["Received", "Received", "Missing", "Missing", "Missing"], ref_prefix="S003-DOC-YO",
            student_number="LLB/2023/0419", programme="LLB Law", level="Level 300", sponsor="Self funded",
            emergency_contact="Ama Owusu, +233 24 555 0142", return_declaration=True,
            approvals=["Pending", "Pending", "Pending"], first_decision=0,
            history=[h(2, "Request raised", "Yaw Owusu created the request.", 16, 40)],
        )
    )

    # 6. Student, pending approvals; guardian consent waived by exception, welfare check open.
    specs.append(
        dict(
            direction="Outbound", category="Student outbound travel", traveller="Yaw Owusu",
            purpose="Exchange semester, University of Cape Town", destination="Cape Town, South Africa",
            start=d(75), end=d(180), requester="Yaw Owusu", status="Pending approvals", kind="student", submitted=6,
            evidence=["Received", "Received", "Received", "Received", "Exception"], ref_prefix="S003-DOC-YS",
            evidence_extra={4: "Student is over 18; guardian consent is not required."},
            student_number="LLB/2023/0419", programme="LLB Law", level="Level 300",
            sponsor="CLET Scholarship Fund", emergency_contact="Ama Owusu, +233 24 555 0142", return_declaration=True,
            approvals=["Approved", "Pending", "Pending"], first_decision=4,
            estimate=_estimate(30, 650, 9800, 21000, 1500),
            integrations={"S003": ("Pending", None, None)},
            history=[
                h(6, "Request raised", "Yaw Owusu created the request.", 11, 2),
                h(6, "Moved to Submitted", "Yaw Owusu advanced the request.", 11, 30),
                h(5, "Moved to Screening", f"{DTI} advanced the request."),
                h(5, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(4, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(4, "Estimate saved", f"GHS 32,800.00 at {RATE_VERSION} - {DTI}", 15, 0),
            ],
        )
    )

    # 7. Submitted official request (the original core-seed outbound record).
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Yaw Owusu",
            purpose="Bilateral legal education mission", destination="Nairobi, Kenya", start=d(35), end=d(40),
            requester=DTI, status="Submitted", kind="staff", submitted=1,
            evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-YM",
            approvals=["Pending", "Pending", "Pending"], first_decision=0,
            history=[
                h(1, "Request raised", f"{DTI} created the request.", 14, 0),
                h(1, "Moved to Submitted", f"{DTI} advanced the request.", 14, 20),
            ],
        )
    )

    # 8. Inbound delegation in screening.
    specs.append(
        dict(
            direction="Inbound", category="Delegation visa support", traveller="Hon. Justice Fatima Bello",
            nationality="Nigerian", purpose="Judicial exchange delegation", destination="Accra, Ghana",
            host="Judicial Service of Ghana", start=d(28), end=d(32), requester=IR_OFFICER, status="Screening",
            kind="inbound", submitted=3, source_reference="S083-DEL-0201",
            evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-FB",
            approvals=["Pending", "Pending", "Pending"], first_decision=0,
            integrations={"S083": ("Complete", "S083-DEL-0201", None)},
            history=[
                h(3, "Request raised", f"{IR_OFFICER} created the request.", 9, 5),
                h(3, "Moved to Submitted", f"{IR_OFFICER} advanced the request.", 9, 45),
                h(2, "Moved to Screening", f"{DTI} advanced the request.", 8, 50),
            ],
        )
    )

    # 9. Inbound, support letter issued, accommodation and GIS tracking.
    specs.append(
        dict(
            direction="Inbound", category="Examiner visa support", traveller="Prof. Ibrahim Diallo",
            nationality="Senegalese", purpose="External examiner, LLM viva panel", destination="Accra, Ghana",
            host="CLET Registrar", start=d(21), end=d(25), requester=IR_OFFICER, status="Support issued",
            kind="inbound", submitted=14, source_reference="S083-DEL-0188",
            evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-ID",
            approvals=["Approved", "Approved", "Approved"], first_decision=12,
            estimate=_estimate(5, 350, 5200, 3600),
            documents=[("Support letter", 4, "Current")],
            integrations={
                "S083": ("Complete", "S083-DEL-0188", None),
                "GIS": ("Complete", "GIS-REQ-8790", "Visa on arrival confirmed."),
                "S031": ("Pending", None, "Guest house booking requested."),
                "S003": ("Complete", "S003-LTR-7731", None),
                "S074": ("Complete", "S074-COM-4455", None),
            },
            notifications=[("Support letter issued", "Prof. Ibrahim Diallo", "Delivered", 4)],
            signatory=SENIOR,
            history=[
                h(14, "Request raised", f"{IR_OFFICER} created the request.", 9, 0),
                h(14, "Moved to Submitted", f"{IR_OFFICER} advanced the request."),
                h(13, "Moved to Screening", f"{DTI} advanced the request."),
                h(13, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(12, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(11, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(10, "IR protocol clearance approved", f"{IR_OFFICER}: Approved.", 12, 15),
                h(4, "Support letter issued", f"S084 support letter signed by {SENIOR}.", 11, 30),
            ],
        )
    )

    # 10. Outbound, trip finished last week; awaiting closure.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Samuel Ofori",
            purpose="Commonwealth legal education forum", destination="Lusaka, Zambia", start=d(-12), end=d(-7),
            requester="Samuel Ofori", status="Completed", kind="staff", submitted=32,
            source_reference="S140-EMP-0117", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-SO",
            approvals=["Approved", "Approved", "Approved"], first_decision=30,
            estimate=_estimate(6, 700, 8100, 6300),
            documents=[("Travel authorisation", 24, "Current")],
            integrations={
                "S140": ("Complete", "S140-EMP-0117", None),
                "S144": ("Complete", "S144-EST-2874", None),
                "S003": ("Complete", "S003-DOC-6488", None),
                "S074": ("Complete", "S074-COM-4302", None),
            },
            notifications=[("Travel authorisation issued", "Samuel Ofori", "Delivered", 24)],
            signatory=SENIOR,
            history=[
                h(32, "Request raised", "Samuel Ofori created the request.", 9, 0),
                h(32, "Moved to Submitted", "Samuel Ofori advanced the request."),
                h(31, "Moved to Screening", f"{DTI} advanced the request."),
                h(31, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(30, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(29, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(28, "RMF cost review approved", f"{RMF}: Approved.", 12, 15),
                h(24, "Travel authorisation issued", f"S084 travel authorisation signed by {SENIOR}.", 11, 30),
                h(6, "Moved to Completed", f"{DTI} advanced the request.", 9, 30),
            ],
        )
    )

    # 11. Outbound, closed with a linked claim.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Grace Tetteh",
            purpose="Legal aid clinic benchmarking visit", destination="Kampala, Uganda", start=d(-45), end=d(-40),
            requester="Grace Tetteh", status="Closed", kind="staff", submitted=62,
            source_reference="S140-EMP-0061", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-GT",
            approvals=["Approved", "Approved", "Approved"], first_decision=60,
            estimate=_estimate(5, 700, 6900, 5100),
            documents=[("Travel authorisation", 54, "Current")],
            integrations={
                "S140": ("Complete", "S140-EMP-0061", None),
                "S144": ("Complete", "S144-CLM-3021", "Claim settled."),
                "S003": ("Complete", "S003-DOC-6102", None),
                "S074": ("Complete", "S074-COM-4120", None),
            },
            notifications=[("Travel authorisation issued", "Grace Tetteh", "Delivered", 54)],
            signatory=SENIOR,
            closure={
                "outcome": "Travel completed as authorised; claim settled.",
                "actualStartDate": d(-45).isoformat(),
                "actualEndDate": d(-40).isoformat(),
                "claimReference": "S144-CLM-3021",
                "unresolvedActions": None,
                "closedAt": _stamp(now, 33, 15, 0),
            },
            history=[
                h(62, "Request raised", "Grace Tetteh created the request.", 9, 0),
                h(62, "Moved to Submitted", "Grace Tetteh advanced the request."),
                h(61, "Moved to Screening", f"{DTI} advanced the request."),
                h(61, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(60, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(59, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(58, "RMF cost review approved", f"{RMF}: Approved.", 12, 15),
                h(54, "Travel authorisation issued", f"S084 travel authorisation signed by {SENIOR}.", 11, 30),
                h(38, "Moved to Completed", f"{DTI} advanced the request.", 9, 30),
                h(33, "Request closed", f"{DTI}: Travel completed as authorised; claim settled.", 15, 0),
            ],
        )
    )

    # 12. Inbound, rejected by the senior approver.
    specs.append(
        dict(
            direction="Inbound", category="Exchange student support", traveller="Lerato Dlamini",
            nationality="Eswatini", purpose="Exchange semester", destination="Accra, Ghana",
            host="CLET Academic Affairs", start=d(60), end=d(190), requester=IR_OFFICER, status="Rejected",
            kind="inbound", submitted=11, evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-LD",
            approvals=["Approved", "Rejected", "Superseded"], first_decision=9,
            approval_comments={1: "The nomination was not endorsed by the partner institution."},
            history=[
                h(11, "Request raised", f"{IR_OFFICER} created the request.", 9, 0),
                h(11, "Moved to Submitted", f"{IR_OFFICER} advanced the request."),
                h(10, "Moved to Screening", f"{DTI} advanced the request."),
                h(10, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(9, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(8, "Senior approver rejected", f"{SENIOR}: The nomination was not endorsed by the partner institution.", 10, 55),
            ],
        )
    )

    # 13. Outbound, cancelled after authorisation; cancellation notice failed to send.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Daniel Owusu",
            purpose="West African legal reform summit", destination="Abuja, Nigeria", start=d(9), end=d(12),
            requester="Daniel Owusu", status="Cancelled", kind="staff", submitted=21,
            source_reference="S140-EMP-0033", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-DO",
            approvals=["Approved", "Approved", "Approved"], first_decision=19,
            estimate=_estimate(3, 700, 5400, 2800),
            documents=[("Travel authorisation", 14, "Superseded")],
            integrations={
                "S140": ("Complete", "S140-EMP-0033", None),
                "S144": ("Failed", None, "Estimate withdrawal was rejected by S144; retry required."),
                "S003": ("Complete", "S003-DOC-6540", None),
            },
            notifications=[
                ("Travel authorisation issued", "Daniel Owusu", "Delivered", 14),
                ("Travel request cancelled", "Daniel Owusu", "Failed", 2),
            ],
            signatory=SENIOR,
            cancellation_reason="Summit postponed by the host to next quarter.",
            history=[
                h(21, "Request raised", "Daniel Owusu created the request.", 9, 0),
                h(21, "Moved to Submitted", "Daniel Owusu advanced the request."),
                h(20, "Moved to Screening", f"{DTI} advanced the request."),
                h(20, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(19, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(18, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(17, "RMF cost review approved", f"{RMF}: Approved.", 12, 15),
                h(14, "Travel authorisation issued", f"S084 travel authorisation signed by {SENIOR}.", 11, 30),
                h(2, "Request cancelled", f"{DTI}: Summit postponed by the host to next quarter.", 13, 0),
            ],
        )
    )

    # 14. Inbound, amended after approval: decisions reset, letter superseded, back in approvals.
    specs.append(
        dict(
            direction="Inbound", category="Examiner visa support", traveller="Dr. Chinedu Eze",
            nationality="Nigerian", purpose="External examiner, bar course moderation", destination="Accra, Ghana",
            host="Ghana School of Law", start=d(30), end=d(34), requester=IR_OFFICER, status="Pending approvals",
            kind="inbound", submitted=18, source_reference="S083-DEL-0179",
            evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-CE",
            approvals=["Pending", "Pending", "Pending"], first_decision=0,
            estimate=_estimate(4, 350, 5000, 3200),
            documents=[("Support letter", 9, "Superseded")],
            integrations={
                "S083": ("Complete", "S083-DEL-0179", None),
                "GIS": ("Pending", "GIS-REQ-8774", "Dates changed; liaison notified."),
                "S003": ("Complete", "S003-LTR-7702", None),
            },
            notifications=[("Support letter issued", "Dr. Chinedu Eze", "Delivered", 9)],
            signatory=SENIOR,
            last_change_reason="Examination board moved the moderation dates by one week.",
            history=[
                h(18, "Request raised", f"{IR_OFFICER} created the request.", 9, 0),
                h(18, "Moved to Submitted", f"{IR_OFFICER} advanced the request."),
                h(17, "Moved to Screening", f"{DTI} advanced the request."),
                h(17, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(16, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(15, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(14, "IR protocol clearance approved", f"{IR_OFFICER}: Approved.", 12, 15),
                h(9, "Support letter issued", f"S084 support letter signed by {SENIOR}.", 11, 30),
                h(1, "Itinerary amended", f"{DTI}: Examination board moved the moderation dates by one week.", 9, 45),
            ],
        )
    )

    # 15. Outbound draft, urgent: nothing collected, leaves in five days.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Kofi Adjei",
            purpose="Urgent arbitration hearing", destination="Lome, Togo", start=d(5), end=d(7),
            requester="Kofi Adjei", status="Draft", kind="staff", submitted=None,
            evidence=["Missing", "Missing", "Missing"], ref_prefix="S003-DOC-KJ",
            approvals=["Pending", "Pending", "Pending"], first_decision=0,
            history=[h(0, "Request raised", "Kofi Adjei created the request.", 8, 20)],
        )
    )

    # 16. Outbound, senior decision outstanding for longer than the escalation window.
    specs.append(
        dict(
            direction="Outbound", category="Official staff travel", traveller="Abena Serwaa",
            purpose="Curriculum accreditation review", destination="Dakar, Senegal", start=d(18), end=d(23),
            requester="Abena Serwaa", status="Pending approvals", kind="staff", submitted=10,
            source_reference="S140-EMP-0155", evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-AS",
            approvals=["Approved", "Pending", "Pending"], first_decision=8,
            estimate=_estimate(5, 700, 9200, 6400),
            integrations={"S140": ("Complete", "S140-EMP-0155", None)},
            history=[
                h(10, "Request raised", "Abena Serwaa created the request.", 9, 0),
                h(10, "Moved to Submitted", "Abena Serwaa advanced the request."),
                h(9, "Moved to Screening", f"{DTI} advanced the request."),
                h(9, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(8, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(8, "Estimate saved", f"GHS 19,100.00 at {RATE_VERSION} - {DTI}", 15, 0),
            ],
        )
    )

    # 17. Inbound, support letter issued but the S074 notification and handoff failed.
    specs.append(
        dict(
            direction="Inbound", category="Exchange student support", traveller="Thabo Nkosi",
            nationality="South African", purpose="Exchange semester", destination="Accra, Ghana",
            host="CLET Academic Affairs", start=d(48), end=d(170), requester=IR_OFFICER, status="Support issued",
            kind="inbound", submitted=15, evidence=["Received", "Received", "Received"], ref_prefix="S003-DOC-TN",
            approvals=["Approved", "Approved", "Approved"], first_decision=13,
            documents=[("Support letter", 3, "Current")],
            integrations={
                "GIS": ("Pending", "GIS-REQ-8821", None),
                "S031": ("Failed", None, "Accommodation service timed out; retry the handoff."),
                "S003": ("Complete", "S003-LTR-7745", None),
                "S074": ("Failed", None, "Notification relay returned an error."),
            },
            notifications=[("Support letter issued", "Thabo Nkosi", "Failed", 3), ("Support letter copy to host", "CLET Academic Affairs", "Pending", 3)],
            signatory=SENIOR,
            history=[
                h(15, "Request raised", f"{IR_OFFICER} created the request.", 9, 0),
                h(15, "Moved to Submitted", f"{IR_OFFICER} advanced the request."),
                h(14, "Moved to Screening", f"{DTI} advanced the request."),
                h(14, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(13, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(12, "Senior approver approved", f"{SENIOR}: Approved.", 11, 15),
                h(11, "IR protocol clearance approved", f"{IR_OFFICER}: Approved.", 12, 15),
                h(3, "Support letter issued", f"S084 support letter signed by {SENIOR}.", 11, 30),
            ],
        )
    )

    # 18. Student outbound, trip finished and closed (gives the student portal a history).
    specs.append(
        dict(
            direction="Outbound", category="Student outbound travel", traveller="Yaw Owusu",
            purpose="Regional moot court finals", destination="Nairobi, Kenya", start=d(-70), end=d(-65),
            requester="Yaw Owusu", status="Closed", kind="student", submitted=90,
            evidence=["Received", "Received", "Received", "Received", "Received"], ref_prefix="S003-DOC-YC",
            student_number="LLB/2023/0419", programme="LLB Law", level="Level 300", sponsor="Self funded",
            emergency_contact="Ama Owusu, +233 24 555 0142", return_declaration=True,
            approvals=["Approved", "Approved", "Approved"], first_decision=88,
            estimate=_estimate(5, 650, 7400, 4800),
            documents=[("Travel authorisation", 80, "Current")],
            integrations={"S003": ("Complete", "S003-DOC-5990", None), "S074": ("Complete", "S074-COM-3988", None)},
            notifications=[("Travel authorisation issued", "Yaw Owusu", "Delivered", 80)],
            signatory=SENIOR,
            closure={
                "outcome": "Student returned as declared; no unresolved actions.",
                "actualStartDate": d(-70).isoformat(),
                "actualEndDate": d(-65).isoformat(),
                "claimReference": None,
                "unresolvedActions": None,
                "closedAt": _stamp(now, 60, 15, 0),
            },
            history=[
                h(90, "Request raised", "Yaw Owusu created the request.", 9, 0),
                h(90, "Moved to Submitted", "Yaw Owusu advanced the request."),
                h(89, "Moved to Screening", f"{DTI} advanced the request."),
                h(89, "Moved to Pending approvals", f"{DTI} advanced the request."),
                h(88, "Line manager approved", f"{LINE_MANAGER}: Approved.", 10, 15),
                h(87, "Student welfare (P&C) approved", f"{WELFARE}: Approved.", 11, 15),
                h(86, "Senior approver approved", f"{SENIOR}: Approved.", 12, 15),
                h(80, "Travel authorisation issued", f"S084 travel authorisation signed by {SENIOR}.", 11, 30),
                h(64, "Moved to Completed", f"{DTI} advanced the request.", 9, 30),
                h(60, "Request closed", f"{DTI}: Student returned as declared; no unresolved actions.", 15, 0),
            ],
        )
    )
    return specs


async def seed(session) -> None:
    # Idempotent: the register is owned by this module, so any existing request means it has run
    # (or the workspace is already in use) and nothing is added.
    if await session.scalar(select(func.count()).select_from(TravelRequest)):
        return

    now = dt.datetime.now(dt.UTC)
    today = dt.date.today()

    if session.get_bind().dialect.name == "sqlite":
        # Databases migrated before the migration stored the default policy id in 32-hex form hold a
        # hyphenated id, which the ORM's UPDATE cannot match. Normalise it so the policy can be edited.
        await session.execute(text("UPDATE travel_policy SET id = replace(id, '-', '') WHERE id LIKE '%-%'"))
    policy = await session.scalar(select(TravelPolicy).limit(1))
    if policy is None:
        session.add(
            TravelPolicy(
                policy_version="TRV-4.2",
                rate_version=RATE_VERSION,
                currency="GHS",
                daily_rates={"Regional": 1200.0, "Continental": 1800.0, "International": 2400.0},
                support_template=TEMPLATE,
                authorisation_template=TEMPLATE,
                escalation_days=3,
                updated_by=DTI,
            )
        )

    specs = _specs(today, now)
    # Oldest first so references ascend with age, as they would in real use.
    specs.sort(key=lambda spec: _parse(spec["history"][0]["at"]))
    for sequence, spec in enumerate(specs, start=1):
        direction = spec["direction"]
        inbound = direction == "Inbound"
        kind = spec["kind"]
        reference = f"S084-{today.year}-{sequence:04d}"
        history = spec["history"]
        version = len(history)

        documents = []
        for number, (doc_type, days_ago, status) in enumerate(spec.get("documents", []), start=1):
            doc = _document(reference, doc_type == "Support letter", number, spec.get("signatory", SENIOR), now, days_ago, status)
            documents.append(doc)
        notifications = [
            _notification(reference, number, subject, recipient, status, now, days_ago)
            for number, (subject, recipient, status, days_ago) in enumerate(spec.get("notifications", []), start=1)
        ]

        request = TravelRequest(
            reference=reference,
            direction=direction,
            category=spec["category"],
            traveller=spec["traveller"],
            nationality=spec.get("nationality"),
            purpose=spec["purpose"],
            destination=spec["destination"],
            host=spec.get("host"),
            start_date=spec["start"],
            end_date=spec["end"],
            owner=spec["traveller"],
            requester=spec["requester"],
            student_number=spec.get("student_number"),
            programme=spec.get("programme"),
            level=spec.get("level"),
            sponsor=spec.get("sponsor"),
            emergency_contact=spec.get("emergency_contact"),
            return_declaration=spec.get("return_declaration"),
            status=spec["status"],
            submitted_at=(today - dt.timedelta(days=spec["submitted"])).isoformat() if spec.get("submitted") else None,
            source_reference=spec.get("source_reference"),
            policy_version="TRV-4.2",
            record_version=version,
            estimate=spec.get("estimate"),
            closure=spec.get("closure"),
            cancellation_reason=spec.get("cancellation_reason"),
            last_change_reason=spec.get("last_change_reason"),
            evidence=_evidence(kind, spec["evidence"], spec["ref_prefix"], LINE_MANAGER if not inbound else IR_OFFICER, spec.get("evidence_extra")),
            approvals=_approvals(kind, spec["approvals"], now, spec["first_decision"], max(version - 2, 1), spec.get("approval_comments")),
            integrations=_integrations(
                "inbound" if inbound else "outbound",
                spec.get("integrations", {}),
                now,
                max(spec["first_decision"] - 2, 0),
            ),
            issued_documents=documents,
            notifications=notifications,
            history=history,
            created_at=_parse(history[0]["at"]),
            updated_at=_parse(history[-1]["at"]),
        )
        request.next_action = (
            "No action outstanding"
            if spec["status"] in {"Closed", "Rejected", "Cancelled"}
            else rules.next_action_for(request)
        )
        session.add(request)
