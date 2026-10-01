"""
S084 Visa & Travel Authorisation business rules.

The frontend holds the same rules in
`apps/travel-authorisation/src/features/requests/domain.ts`; this module is the
authority. A request moves:

    Draft ─submit─> Submitted ─> Screening ─> Pending approvals ─(all approved)─>
    Approved ─issue─> Support issued | Travel authorised ─> Completed ─> Closed

with `Returned`, `Rejected` and `Cancelled` as exits. Two gates are enforced
here rather than in the router, because both the workspace and the student
self-service route hit them:

* a request cannot leave Draft/Returned while a required evidence line is Missing;
* a document cannot be issued before every approval step is Approved.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.errors import Conflict, ValidationFailed
from app.models.base import utcnow
from app.models.travel import TravelRequest

#: The step that follows a successful `advance` from each status.
FORWARD: dict[str, str] = {
    "Draft": "Submitted",
    "Returned": "Submitted",
    "Submitted": "Screening",
    "Screening": "Pending approvals",
    "Support issued": "Completed",
    "Travel authorised": "Completed",
    "Completed": "Closed",
}

#: Statuses that accept no further workflow movement.
TERMINAL = {"Closed", "Rejected", "Cancelled"}

EDITABLE = {"Draft", "Returned"}


def evidence_for(direction: str, category: str) -> list[dict[str, Any]]:
    """
    The checklist a new request starts with. Student outbound travel carries the
    widest set because S031 requires guardian consent and proof of enrolment.
    """
    if category == "Student outbound travel":
        labels = [
            ("Passport bio page", True),
            ("Travel itinerary", False),
            ("Proof of enrolment", True),
            ("Sponsor or funding confirmation", True),
            ("Parent or guardian consent", True),
        ]
    elif direction == "Inbound":
        labels = [
            ("Passport bio page", True),
            ("Invitation or appointment letter", False),
            ("Travel itinerary", False),
        ]
    else:
        labels = [
            ("Invitation or business case", False),
            ("Travel itinerary", False),
            ("Funding confirmation", True),
        ]
    return [
        {
            "id": f"ev-{index + 1}",
            "label": label,
            "required": True,
            "sensitive": sensitive,
            "status": "Missing",
        }
        for index, (label, sensitive) in enumerate(labels)
    ]


def approvals_for(direction: str, category: str) -> list[dict[str, Any]]:
    """The approval chain. Student travel adds the P&C welfare check."""
    steps = [("Line manager", "Line Manager"), ("Senior approver", "Senior Approver")]
    if category == "Student outbound travel":
        steps.insert(1, ("Student welfare (P&C)", "P&C Reviewer"))
    if direction == "Inbound":
        steps.append(("IR protocol clearance", "IR Officer"))
    return [
        {
            "id": f"ap-{index + 1}",
            "label": label,
            "assignee": assignee,
            "status": "Pending",
        }
        for index, (label, assignee) in enumerate(steps)
    ]


def integrations_for(direction: str) -> list[dict[str, Any]]:
    """
    The downstream systems a request hands off to. CLET owns none of these
    outcomes, so each one carries a status and a reference and nothing more.
    """
    rows = [
        ("S003", "Records management"),
        ("S074", "Notifications"),
        ("S144", "Finance disbursement"),
    ]
    if direction == "Inbound":
        rows.insert(0, ("S083", "IR protocol"))
    return [{"system": system, "label": label, "status": "Not started"} for system, label in rows]


def evidence_ready(request: TravelRequest) -> bool:
    return all(not item.get("required", True) or item.get("status") != "Missing" for item in (request.evidence or []))


def missing_evidence(request: TravelRequest) -> list[str]:
    return [item["label"] for item in (request.evidence or []) if item.get("required", True) and item.get("status") == "Missing"]


def approvals_complete(request: TravelRequest) -> bool:
    return all(step.get("status") in {"Approved", "Not required"} for step in (request.approvals or []))


def next_action_for(request: TravelRequest) -> str:
    status = request.status
    if status in EDITABLE:
        return "Complete evidence checklist" if not evidence_ready(request) else "Submit for screening"
    if status == "Submitted":
        return "Start screening"
    if status == "Screening":
        return "Route for approval"
    if status == "Pending approvals":
        return "Awaiting approval decisions"
    if status == "Approved":
        return "Issue support letter" if request.direction == "Inbound" else "Issue travel authorisation"
    if status in {"Support issued", "Travel authorised"}:
        return "Complete request"
    if status == "Completed":
        return "Close request"
    return "No action outstanding"


def record(request: TravelRequest, title: str, detail: str) -> None:
    """Append a history entry and bump the record version."""
    history = list(request.history or [])
    history.append({"title": title, "detail": detail, "at": utcnow().isoformat().replace("+00:00", "Z")})
    request.history = history
    request.record_version = (request.record_version or 1) + 1
    request.next_action = next_action_for(request)


def guard_editable(request: TravelRequest) -> None:
    if request.status in TERMINAL:
        raise Conflict(
            f"This request is {request.status.lower()} and can no longer be changed.",
            code="TRAVEL_REQUEST_CLOSED",
        )


def advance(request: TravelRequest, actor: str) -> str:
    """Move the request one step forward, enforcing the gates. Returns the new status."""
    guard_editable(request)

    target = FORWARD.get(request.status)
    if target is None:
        raise Conflict(
            f"A request at {request.status} has no next step.",
            code="TRAVEL_NO_TRANSITION",
        )

    if request.status in EDITABLE and not evidence_ready(request):
        raise ValidationFailed(
            "Complete the required evidence before submitting.",
            code="TRAVEL_EVIDENCE_INCOMPLETE",
            field_errors={"evidence": missing_evidence(request)},
        )

    if request.status == "Screening":
        # Routing for approval resets any decision taken against an older
        # version, so an amended itinerary is never approved by omission.
        request.approvals = [
            {**step, "status": "Pending", "decidedAt": None, "comment": None} if step.get("status") != "Not required" else step
            for step in (request.approvals or [])
        ]

    request.status = target
    if target == "Submitted":
        request.submitted_at = dt.date.today().isoformat()
    record(request, f"Moved to {target}", f"{actor} advanced the request.")
    return target


def apply_decision(request: TravelRequest, approval_id: str, decision: str, comment: str, actor: str) -> None:
    """Record one approval decision and settle the request's status."""
    guard_editable(request)
    if request.status != "Pending approvals":
        raise Conflict(
            "Approvals can only be decided while the request is pending approval.",
            code="TRAVEL_NOT_PENDING_APPROVAL",
        )

    # Rebuild the list from fresh dicts. Mutating the loaded ones in place would
    # leave the attribute's old and new values identical, so SQLAlchemy would
    # see no change on this JSON column and never write the decision.
    existing = request.approvals or []
    target = next((step for step in existing if step.get("id") == approval_id), None)
    if target is None:
        raise ValidationFailed("That approval step is not on this request.", code="TRAVEL_STEP_NOT_FOUND")
    if target.get("status") != "Pending":
        raise Conflict("That approval step has already been decided.", code="TRAVEL_STEP_DECIDED")

    decided = {
        **target,
        "status": decision,
        "decidedAt": utcnow().isoformat().replace("+00:00", "Z"),
        "comment": comment,
        "recordVersion": request.record_version,
    }
    steps = [decided if step.get("id") == approval_id else {**step} for step in existing]

    if decision in {"Rejected", "Returned"}:
        request.status = decision
        # Everything still outstanding is moot once one approver rejects or returns.
        steps = [{**step, "status": "Superseded"} if step.get("status") == "Pending" else step for step in steps]
    request.approvals = steps
    target = decided

    if decision == "Approved" and approvals_complete(request):
        request.status = "Approved"

    record(request, f"{target['label']} {decision.lower()}", f"{actor}: {comment}")


def issue_document(request: TravelRequest, signatory: str, template_version: str, actor: str) -> dict[str, Any]:
    """Issue the support letter or travel authorisation, superseding any earlier one."""
    guard_editable(request)
    if request.status != "Approved":
        raise Conflict(
            "A document can only be issued once the request is approved.",
            code="TRAVEL_NOT_APPROVED",
        )
    if not approvals_complete(request):
        raise Conflict("Every approval step must be approved first.", code="TRAVEL_APPROVALS_INCOMPLETE")

    inbound = request.direction == "Inbound"
    doc_type = "Support letter" if inbound else "Travel authorisation"
    documents = [
        {**doc, "status": "Superseded"} if doc.get("status") == "Current" else doc for doc in (request.issued_documents or [])
    ]
    issued = {
        "id": str(uuid.uuid4()),
        "type": doc_type,
        "reference": f"{request.reference}-{'SL' if inbound else 'TA'}{len(documents) + 1:02d}",
        "templateVersion": template_version,
        "signatory": signatory,
        "issuedAt": utcnow().isoformat().replace("+00:00", "Z"),
        "status": "Current",
    }
    documents.append(issued)
    request.issued_documents = documents
    request.status = "Support issued" if inbound else "Travel authorised"
    record(request, f"{doc_type} issued", f"{issued['reference']} signed by {signatory}.")
    return issued


def amend(request: TravelRequest, destination: str, start: dt.date, end: dt.date, reason: str, actor: str) -> None:
    """
    Change the itinerary. Anything already approved goes back for re-approval,
    and a current document is superseded: an approval given against the old
    itinerary must not carry over to the new one.
    """
    guard_editable(request)
    previous = f"{request.destination} {request.start_date}–{request.end_date}"
    request.destination = destination
    request.start_date = start
    request.end_date = end
    request.last_change_reason = reason

    if request.status not in EDITABLE:
        request.approvals = [
            {**step, "status": "Pending", "decidedAt": None, "comment": None} if step.get("status") != "Not required" else step
            for step in (request.approvals or [])
        ]
        request.issued_documents = [
            {**doc, "status": "Superseded"} if doc.get("status") == "Current" else doc for doc in (request.issued_documents or [])
        ]
        request.status = "Pending approvals"

    record(request, "Itinerary amended", f"{actor}: {reason} (was {previous}).")


def cancel(request: TravelRequest, reason: str, actor: str) -> None:
    if request.status in TERMINAL:
        raise Conflict("This request is already closed.", code="TRAVEL_REQUEST_CLOSED")
    request.status = "Cancelled"
    request.cancellation_reason = reason
    request.approvals = [
        {**step, "status": "Superseded"} if step.get("status") == "Pending" else step for step in (request.approvals or [])
    ]
    record(request, "Request cancelled", f"{actor}: {reason}")


def close(request: TravelRequest, closure: dict[str, Any], actor: str) -> None:
    if request.status != "Completed":
        raise Conflict(
            "Only a completed request can be closed.",
            code="TRAVEL_NOT_COMPLETED",
        )
    request.closure = {**closure, "closedAt": utcnow().isoformat().replace("+00:00", "Z")}
    request.status = "Closed"
    record(request, "Request closed", f"{actor}: {closure.get('outcome', '')}")


def set_evidence(request: TravelRequest, index: int, status: str, detail: str | None, actor: str) -> None:
    guard_editable(request)
    items = list(request.evidence or [])
    if index < 0 or index >= len(items):
        raise ValidationFailed("That evidence line is not on this request.", code="TRAVEL_EVIDENCE_NOT_FOUND")
    if status == "Exception" and not (detail or "").strip():
        raise ValidationFailed(
            "Record why the requirement is waived.",
            code="TRAVEL_EXCEPTION_REASON_REQUIRED",
            field_errors={"detail": ["A reason is required for an exception."]},
        )

    item = dict(items[index])
    item["status"] = status
    item["reviewedBy"] = actor
    if status == "Exception":
        item["exceptionReason"] = detail
        item.pop("reference", None)
    elif status == "Received":
        item["reference"] = detail or item.get("reference")
        item.pop("exceptionReason", None)
    else:
        item.pop("reference", None)
        item.pop("exceptionReason", None)
    items[index] = item
    request.evidence = items
    record(request, f"Evidence {status.lower()}", f"{item['label']} — {actor}")


def save_estimate(request: TravelRequest, payload: dict[str, Any], actor: str) -> None:
    """
    Store the pre-travel estimate. This is a planning figure only — S144 owns
    the disbursement, so nothing here moves money.
    """
    guard_editable(request)
    per_diem = float(payload["eligible_days"]) * float(payload["daily_rate"])
    request.estimate = {
        "currency": payload["currency"],
        "perDiem": per_diem,
        "transport": float(payload["transport"]),
        "accommodation": float(payload["accommodation"]),
        "other": float(payload.get("other") or 0),
        "eligibleDays": int(payload["eligible_days"]),
        "dailyRate": float(payload["daily_rate"]),
        "rateVersion": payload["rate_version"],
    }
    total = per_diem + request.estimate["transport"] + request.estimate["accommodation"] + request.estimate["other"]
    record(request, "Estimate saved", f"{payload['currency']} {total:,.2f} at {payload['rate_version']} — {actor}")


def set_integration(
    request: TravelRequest, system: str, status: str, reference: str | None, note: str | None, actor: str
) -> None:
    existing = request.integrations or []
    target = next((row for row in existing if row.get("system") == system), None)
    if target is None:
        raise ValidationFailed("That system is not a handoff for this request.", code="TRAVEL_SYSTEM_NOT_FOUND")
    updated = {
        **target,
        "status": status,
        "reference": reference or target.get("reference"),
        "note": note or target.get("note"),
        "updatedAt": utcnow().isoformat().replace("+00:00", "Z"),
    }
    # New dicts, for the same reason as `apply_decision`.
    request.integrations = [updated if row.get("system") == system else {**row} for row in existing]
    record(request, f"{system} handoff {status.lower()}", f"{target['label']} — {actor}")
