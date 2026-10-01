"""Imports every model so `Base.metadata` (Alembic, tests) sees all tables."""

from app.models.audit import AuditEvent, OutboxEvent  # noqa: F401
from app.models.consultations import Consultation, ConsultationInvitation, ConsultationResponse  # noqa: F401
from app.models.international import IrCorrespondence, IrEngagement, IrGift, IrLetterTemplate  # noqa: F401
from app.models.kol import KolContent, KolEngagement, KolMediaMention, KolProfile  # noqa: F401
from app.models.microsites import Microsite, MicrositeReview, MicrositeTemplate  # noqa: F401
from app.models.partnerships import (  # noqa: F401
    ObligationProgressNote,
    PartnershipAgreement,
    PartnershipHistory,
    PartnershipObligation,
    PartnershipRenewal,
    PartnershipRenewalAlert,
    PartnershipReview,
)
from app.models.stakeholders import Segment, Stakeholder, StakeholderContact, StakeholderEngagement  # noqa: F401
from app.models.travel import TravelPolicy, TravelRequest  # noqa: F401
from app.models.users import User, UserSession  # noqa: F401
