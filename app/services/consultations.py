"""
S088 rules: lifecycle, skip-logic evaluation and response validation.

The server evaluates `visibleIf` exactly like the public form
(`features/consultations/logic.ts`): hidden questions are neither required nor
stored, so a crafted request cannot smuggle answers past the branching.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.models.consultations import Consultation, ConsultationResponse, ConsultationStatus

C = ConsultationStatus

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    C.DRAFT: {C.REVIEW},
    C.REVIEW: {C.DRAFT, C.SCHEDULED},
    C.SCHEDULED: {C.OPEN, C.DRAFT},
    C.OPEN: {C.CLOSED, C.OPEN},  # OPEN → OPEN extends the closing date
    C.CLOSED: {C.OPEN, C.ARCHIVED},
    C.ARCHIVED: set(),
}


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def accepting_responses(consultation: Consultation) -> bool:
    current = now()
    return consultation.status == C.OPEN and _aware(consultation.opens_at) <= current < _aware(consultation.closes_at)


def _condition_holds(condition: dict, answers: dict[str, Any]) -> bool:
    answer = answers.get(condition["questionId"])
    operator, expected = condition["operator"], condition.get("value")
    if operator == "ANSWERED":
        return answer not in (None, "", [])
    if answer in (None, "", []):
        return False
    if operator == "INCLUDES":
        return str(expected) in answer if isinstance(answer, list) else str(expected) == str(answer)
    if operator in ("GREATER_THAN", "LESS_THAN"):
        try:
            left, right = float(answer), float(expected)  # type: ignore[arg-type]
        except TypeError, ValueError:
            return False
        return left > right if operator == "GREATER_THAN" else left < right
    equal = str(answer) == str(expected) if not isinstance(answer, list) else str(expected) in answer
    return equal if operator == "EQUALS" else not equal


def visible_questions(questions: list[dict], answers: dict[str, Any]) -> list[dict]:
    visible: list[dict] = []
    for question in questions:
        conditions = question.get("visibleIf") or []
        if all(_condition_holds(c, answers) for c in conditions):
            visible.append(question)
    return visible


def _options_for(question: dict, language: str) -> set[str]:
    options = set(question.get("options") or [])
    for code, translation in (question.get("translations") or {}).items():
        if code == language:
            options |= set(translation.get("options") or [])
    return options


def validate_answers(questions: list[dict], answers: dict[str, Any], language: str) -> dict[str, Any]:
    """Return the cleaned answers for visible questions or raise with per-question errors."""
    errors: dict[str, list[str]] = {}
    cleaned: dict[str, Any] = {}
    known = {q["id"] for q in questions}
    unknown = [key for key in answers if key not in known]
    if unknown:
        raise ValidationFailed("Answers refer to questions that are not in this consultation.")
    for question in visible_questions(questions, answers):
        qid, qtype = question["id"], question["type"]
        if qtype == "SECTION":
            continue
        value = answers.get(qid)
        if value in (None, "", []):
            if question.get("required"):
                errors[qid] = ["This question is required."]
            continue
        problem = None
        if qtype in ("SHORT_TEXT", "LONG_TEXT"):
            limit = 500 if qtype == "SHORT_TEXT" else 10000
            if not isinstance(value, str) or len(value) > limit:
                problem = f"Enter text up to {limit} characters."
        elif qtype in ("SINGLE_CHOICE", "DROPDOWN"):
            if not isinstance(value, str) or value not in _options_for(question, language):
                problem = "Choose one of the listed options."
        elif qtype == "MULTI_CHOICE":
            options = _options_for(question, language)
            if not isinstance(value, list) or any(item not in options for item in value):
                problem = "Choose from the listed options."
        elif qtype in ("RATING", "NPS", "NUMBER"):
            low = 0 if qtype == "NPS" else question.get("min")
            high = 10 if qtype == "NPS" else question.get("max")
            if qtype == "RATING":
                low, high = low if low is not None else 1, high if high is not None else 5
            try:
                number = float(value)  # type: ignore[arg-type]
            except TypeError, ValueError:
                number = None
            if number is None or isinstance(value, bool):
                problem = "Enter a number."
            elif (low is not None and number < low) or (high is not None and number > high):
                problem = f"Enter a value between {low} and {high}."
            else:
                value = int(number) if number.is_integer() else number
        elif qtype == "DATE":
            try:
                dt.date.fromisoformat(str(value))
            except ValueError:
                problem = "Enter a valid date."
        if problem:
            errors[qid] = [problem]
        else:
            cleaned[qid] = value
    if errors:
        raise ValidationFailed("Some answers need attention.", field_errors=errors)
    return cleaned


async def load(db: AsyncSession, consultation_id: uuid.UUID) -> Consultation:
    row = await db.get(Consultation, consultation_id)
    if row is None:
        raise NotFound("That consultation does not exist.", code="CONSULTATION_NOT_FOUND")
    return row


async def load_public(db: AsyncSession, slug: str) -> Consultation:
    row = await db.scalar(select(Consultation).where(Consultation.slug == slug))
    if row is None or row.status not in C.PUBLIC:
        raise NotFound("That consultation is not available.", code="CONSULTATION_NOT_FOUND")
    return row


async def response_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(ConsultationResponse.consultation_id, func.count())
        .where(ConsultationResponse.consultation_id.in_(ids))
        .group_by(ConsultationResponse.consultation_id)
    )
    return {row[0]: int(row[1]) for row in rows.all()}


def serialize(consultation: Consultation, response_count: int) -> dict:
    return {
        "id": consultation.id,
        "slug": consultation.slug,
        "title": consultation.title,
        "summary": consultation.summary,
        "description": consultation.description,
        "category": consultation.category,
        "status": consultation.status,
        "languages": consultation.languages,
        "opens_at": consultation.opens_at,
        "closes_at": consultation.closes_at,
        "estimated_minutes": consultation.estimated_minutes,
        "anonymous_allowed": consultation.anonymous_allowed,
        "collect_identity": consultation.collect_identity,
        "audience_source": consultation.audience_source,
        "audience_segment_ids": consultation.audience_segment_ids,
        "invited_count": consultation.invited_count,
        "response_count": response_count,
        "questions": consultation.questions,
        "triggers": consultation.triggers,
        "themes": consultation.themes,
        "outcome_summary": consultation.outcome_summary,
        "approved_by": consultation.approved_by,
        "created_at": consultation.created_at,
        "updated_at": consultation.updated_at,
    }


def serialize_public(consultation: Consultation, response_count: int) -> dict:
    """Public view: internal targeting, approver and invitation data are withheld."""
    data = serialize(consultation, response_count)
    data.update(
        {
            "audience_segment_ids": [],
            "invited_count": None,
            "triggers": [],
            "themes": [],
            "approved_by": None,
            "outcome_summary": consultation.outcome_summary if consultation.status == C.CLOSED else None,
        }
    )
    return data
