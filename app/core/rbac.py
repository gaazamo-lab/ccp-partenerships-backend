"""
Role-based access control.

Each user holds one role. Roles map to permissions here and only here — routers
depend on permissions, never on role names. Role names match the frontend
permission matrices (`permissions.ts` in each app).
"""

from __future__ import annotations


class P:
    """Permission constants, `<module>:<action>`."""

    ADMIN_ALL = "admin:*"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"

    # S081 Stakeholder / Partner CRM
    STAKEHOLDERS_READ = "stakeholders:read"
    STAKEHOLDERS_WRITE = "stakeholders:write"
    STAKEHOLDERS_ENGAGE = "stakeholders:engage"
    STAKEHOLDERS_SCREEN = "stakeholders:screen"
    STAKEHOLDERS_IMPORT = "stakeholders:import"
    SEGMENTS_WRITE = "segments:write"

    # S082 MOU & Partnership Lifecycle Tracker
    PARTNERSHIPS_READ = "partnerships:read"
    PARTNERSHIPS_CREATE = "partnerships:create"
    PARTNERSHIPS_EDIT = "partnerships:edit"
    PARTNERSHIPS_OBLIGATIONS = "partnerships:obligations"
    PARTNERSHIPS_REVIEWS = "partnerships:reviews"
    PARTNERSHIPS_LIFECYCLE = "partnerships:lifecycle"
    PARTNERSHIPS_IMPORT = "partnerships:import"
    PARTNERSHIPS_EXPORT = "partnerships:export"

    # S088 Consultations
    CONSULTATIONS_READ = "consultations:read"
    CONSULTATIONS_WRITE = "consultations:write"
    CONSULTATIONS_APPROVE = "consultations:approve"
    CONSULTATIONS_INVITE = "consultations:invite"
    CONSULTATIONS_ANALYSE = "consultations:analyse"

    # S092 KOL tracker
    KOL_READ = "kol:read"
    KOL_WRITE = "kol:write"

    # S091 Donor microsites
    MICROSITES_READ = "microsites:read"
    MICROSITES_WRITE = "microsites:write"
    MICROSITES_REVIEW = "microsites:review"
    MICROSITES_PUBLISH = "microsites:publish"

    # S084 Visa & Travel Authorisation
    TRAVEL_READ = "travel:read"
    TRAVEL_CREATE = "travel:create"
    TRAVEL_OPERATE = "travel:operate"
    TRAVEL_APPROVE = "travel:approve"
    TRAVEL_CONFIGURE = "travel:configure"

    # S083 International relations
    IR_READ = "ir:read"
    IR_WRITE = "ir:write"
    IR_APPROVE = "ir:approve"
    IR_CORRESPONDENCE = "ir:correspondence"
    IR_TEMPLATES = "ir:templates"


_READ_ALL = {
    P.STAKEHOLDERS_READ,
    P.PARTNERSHIPS_READ,
    P.PARTNERSHIPS_EXPORT,
    P.CONSULTATIONS_READ,
    P.KOL_READ,
    P.MICROSITES_READ,
    P.IR_READ,
    P.TRAVEL_READ,
}

_S081_MANAGE = {
    P.STAKEHOLDERS_READ,
    P.STAKEHOLDERS_WRITE,
    P.STAKEHOLDERS_ENGAGE,
    P.STAKEHOLDERS_SCREEN,
    P.STAKEHOLDERS_IMPORT,
    P.SEGMENTS_WRITE,
}
_S082_MANAGE = {
    P.PARTNERSHIPS_READ,
    P.PARTNERSHIPS_CREATE,
    P.PARTNERSHIPS_EDIT,
    P.PARTNERSHIPS_OBLIGATIONS,
    P.PARTNERSHIPS_REVIEWS,
    P.PARTNERSHIPS_LIFECYCLE,
    P.PARTNERSHIPS_IMPORT,
    P.PARTNERSHIPS_EXPORT,
}
_S088_MANAGE = {
    P.CONSULTATIONS_READ,
    P.CONSULTATIONS_WRITE,
    P.CONSULTATIONS_APPROVE,
    P.CONSULTATIONS_INVITE,
    P.CONSULTATIONS_ANALYSE,
}
_S091_MANAGE = {P.MICROSITES_READ, P.MICROSITES_WRITE, P.MICROSITES_REVIEW, P.MICROSITES_PUBLISH}
_S092_MANAGE = {P.KOL_READ, P.KOL_WRITE}
_S083_MANAGE = {P.IR_READ, P.IR_WRITE, P.IR_APPROVE, P.IR_CORRESPONDENCE, P.IR_TEMPLATES}
_S084_MANAGE = {
    P.TRAVEL_READ,
    P.TRAVEL_CREATE,
    P.TRAVEL_OPERATE,
    P.TRAVEL_APPROVE,
    P.TRAVEL_CONFIGURE,
}


class Role:
    SYSTEM_ADMINISTRATOR = "System Administrator"
    CRM_ADMINISTRATOR = "CRM Administrator"
    PARTNERSHIPS_MANAGER = "CCP Partnerships Manager"
    PARTNERSHIPS_OFFICER = "Partnerships Officer"
    REGISTRAR = "Registrar"
    IR_OFFICER = "IR Officer"
    CORRESPONDENCE_OFFICER = "Correspondence Officer"
    IR_APPROVER = "IR Approver"
    CONTENT_MANAGER = "Content Manager"
    RMF_REVIEWER = "RMF Reviewer"
    CONSULTATION_MANAGER = "Consultation Manager"
    EXECUTIVE_VIEWER = "Executive Viewer"
    AUDITOR = "Auditor"
    # S084 Visa & Travel Authorisation
    TRAVELLER = "Traveller"
    LINE_MANAGER = "Line Manager"
    SENIOR_APPROVER = "Senior Approver"
    PC_REVIEWER = "P&C Reviewer"
    DTI_ADMINISTRATOR = "DTI Administrator"

    ALL = [
        SYSTEM_ADMINISTRATOR,
        CRM_ADMINISTRATOR,
        PARTNERSHIPS_MANAGER,
        PARTNERSHIPS_OFFICER,
        REGISTRAR,
        IR_OFFICER,
        CORRESPONDENCE_OFFICER,
        IR_APPROVER,
        CONTENT_MANAGER,
        RMF_REVIEWER,
        CONSULTATION_MANAGER,
        EXECUTIVE_VIEWER,
        AUDITOR,
        TRAVELLER,
        LINE_MANAGER,
        SENIOR_APPROVER,
        PC_REVIEWER,
        DTI_ADMINISTRATOR,
    ]


ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.SYSTEM_ADMINISTRATOR: {P.ADMIN_ALL},
    Role.CRM_ADMINISTRATOR: _S081_MANAGE
    | _S082_MANAGE
    | _S088_MANAGE
    | _S091_MANAGE
    | _S092_MANAGE
    | _S083_MANAGE
    | _S084_MANAGE
    | {P.AUDIT_READ},
    Role.PARTNERSHIPS_MANAGER: _S081_MANAGE | _S082_MANAGE | _S088_MANAGE | _S091_MANAGE | _S092_MANAGE | _READ_ALL,
    Role.PARTNERSHIPS_OFFICER: (_S081_MANAGE - {P.STAKEHOLDERS_SCREEN})
    | _S092_MANAGE
    | {P.CONSULTATIONS_READ, P.CONSULTATIONS_WRITE, P.PARTNERSHIPS_READ, P.MICROSITES_READ},
    Role.REGISTRAR: {
        P.PARTNERSHIPS_READ,
        P.PARTNERSHIPS_EDIT,
        P.PARTNERSHIPS_REVIEWS,
        P.PARTNERSHIPS_LIFECYCLE,
        P.PARTNERSHIPS_EXPORT,
        P.STAKEHOLDERS_READ,
        P.CONSULTATIONS_READ,
        P.CONSULTATIONS_APPROVE,
    },
    Role.IR_OFFICER: {
        P.IR_READ,
        P.IR_WRITE,
        P.STAKEHOLDERS_READ,
        P.STAKEHOLDERS_ENGAGE,
        P.TRAVEL_READ,
        P.TRAVEL_CREATE,
        P.TRAVEL_OPERATE,
    },
    Role.CORRESPONDENCE_OFFICER: {P.IR_READ, P.IR_CORRESPONDENCE, P.IR_TEMPLATES, P.STAKEHOLDERS_READ},
    Role.IR_APPROVER: {P.IR_READ, P.IR_APPROVE, P.STAKEHOLDERS_READ},
    Role.CONTENT_MANAGER: {P.MICROSITES_READ, P.MICROSITES_WRITE, P.STAKEHOLDERS_READ},
    Role.RMF_REVIEWER: {
        P.MICROSITES_READ,
        P.MICROSITES_REVIEW,
        P.MICROSITES_PUBLISH,
        P.STAKEHOLDERS_READ,
        P.TRAVEL_READ,
        P.TRAVEL_APPROVE,
    },
    Role.CONSULTATION_MANAGER: _S088_MANAGE | {P.STAKEHOLDERS_READ},
    Role.EXECUTIVE_VIEWER: set(_READ_ALL),
    Role.AUDITOR: _READ_ALL | {P.AUDIT_READ},
    # S084. A traveller may raise and edit their own request but never approve it;
    # record scoping to "own requests" is applied in the router, not here.
    Role.TRAVELLER: {P.TRAVEL_READ, P.TRAVEL_CREATE},
    Role.LINE_MANAGER: {P.TRAVEL_READ, P.TRAVEL_APPROVE},
    Role.SENIOR_APPROVER: {P.TRAVEL_READ, P.TRAVEL_APPROVE},
    Role.PC_REVIEWER: {P.TRAVEL_READ, P.TRAVEL_APPROVE},
    Role.DTI_ADMINISTRATOR: _S084_MANAGE | {P.AUDIT_READ},
}


def permissions_for_role(role: str) -> set[str]:
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(permissions: set[str], permission: str) -> bool:
    return P.ADMIN_ALL in permissions or permission in permissions
