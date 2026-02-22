"""
Rule repository — all database access for jurisdiction rules.

Functions operate on:
  JurisdictionRuleModel    — active building-code rules
  BuildingCodeDocumentModel — uploaded PDF source documents
  ExtractedRuleModel        — LLM-extracted rules awaiting human review

All async functions accept an AsyncSession as the first argument (injected
by FastAPI's get_session dependency or obtained from AsyncSessionLocal in
scripts / background jobs).

Multi-tenancy: every query that touches firm-scoped data (documents,
extracted rules) requires firm_id and filters on it. JurisdictionRuleModel
is global (shared across firms), but can only be populated by firm_admin.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.db.models import (
    BuildingCodeDocumentModel,
    ExtractedRuleModel,
    JurisdictionRuleModel,
)
from civilengineer.schemas.rules import DesignRule, RuleCategory, Severity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JurisdictionRuleModel — active rules
# ---------------------------------------------------------------------------


async def get_active_rules(
    session: AsyncSession,
    jurisdiction: str,
    code_version: str | None = None,
) -> list[JurisdictionRuleModel]:
    """
    Return all active rules for a jurisdiction, optionally filtered by version.

    Ordered by category then rule_id for deterministic output.
    """
    stmt = (
        select(JurisdictionRuleModel)
        .where(JurisdictionRuleModel.jurisdiction == jurisdiction)
        .where(JurisdictionRuleModel.is_active == True)  # noqa: E712
        .where(JurisdictionRuleModel.superseded_by == None)  # noqa: E711
        .order_by(JurisdictionRuleModel.category, JurisdictionRuleModel.rule_id)
    )
    if code_version is not None:
        stmt = stmt.where(JurisdictionRuleModel.code_version == code_version)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_rule(
    session: AsyncSession,
    rule_id: str,
) -> JurisdictionRuleModel | None:
    """Fetch a single rule by rule_id (regardless of active status)."""
    result = await session.execute(
        select(JurisdictionRuleModel).where(JurisdictionRuleModel.rule_id == rule_id)
    )
    return result.scalar_one_or_none()


async def upsert_rule(
    session: AsyncSession,
    rule: DesignRule,
    source_doc_id: str | None = None,
) -> JurisdictionRuleModel:
    """
    Insert or update a JurisdictionRuleModel from a DesignRule.

    If a rule with rule_id already exists, its fields are updated in place.
    Sets effective_from to now() only on initial insert.
    """
    existing = await get_rule(session, rule.rule_id)

    if existing is not None:
        # Update mutable fields only
        existing.name = rule.name
        existing.description = rule.description
        existing.category = rule.category.value
        existing.severity = rule.severity.value
        existing.rule_type = rule.rule_type
        existing.applies_to = rule.applies_to
        existing.numeric_value = rule.numeric_value
        existing.unit = rule.unit
        existing.reference_rooms = rule.reference_rooms
        existing.tags = rule.tags
        existing.embedding_text = rule.embedding_text
        existing.source_section = rule.source_section
        existing.is_active = rule.is_active
        if source_doc_id:
            existing.source_doc_id = source_doc_id
        session.add(existing)
        return existing

    model = JurisdictionRuleModel(
        rule_id=rule.rule_id,
        jurisdiction=rule.jurisdiction,
        code_version=rule.code_version,
        source_doc_id=source_doc_id,
        source_section=rule.source_section,
        category=rule.category.value,
        severity=rule.severity.value,
        rule_type=rule.rule_type,
        name=rule.name,
        description=rule.description,
        applies_to=rule.applies_to,
        numeric_value=rule.numeric_value,
        unit=rule.unit,
        reference_rooms=rule.reference_rooms,
        embedding_text=rule.embedding_text,
        tags=rule.tags,
        is_active=rule.is_active,
        effective_from=datetime.now(UTC),
    )
    session.add(model)
    return model


async def supersede_rule(
    session: AsyncSession,
    old_rule_id: str,
    new_rule_id: str,
) -> None:
    """
    Mark old_rule_id as superseded by new_rule_id and deactivate it.

    Does nothing if old_rule_id does not exist.
    """
    old = await get_rule(session, old_rule_id)
    if old is None:
        logger.warning("supersede_rule: rule %s not found; skipping.", old_rule_id)
        return
    old.superseded_by = new_rule_id
    old.is_active = False
    session.add(old)
    logger.info("Rule %s superseded by %s", old_rule_id, new_rule_id)


# ---------------------------------------------------------------------------
# BuildingCodeDocumentModel — uploaded PDFs
# ---------------------------------------------------------------------------


async def get_documents(
    session: AsyncSession,
    firm_id: str,
    jurisdiction: str | None = None,
    status: str | None = None,
) -> list[BuildingCodeDocumentModel]:
    """
    List building code documents for a firm, with optional filters.

    Always filtered by firm_id (multi-tenancy).
    """
    stmt = (
        select(BuildingCodeDocumentModel)
        .where(BuildingCodeDocumentModel.firm_id == firm_id)
        .order_by(BuildingCodeDocumentModel.uploaded_at.desc())
    )
    if jurisdiction is not None:
        stmt = stmt.where(BuildingCodeDocumentModel.jurisdiction == jurisdiction)
    if status is not None:
        stmt = stmt.where(BuildingCodeDocumentModel.status == status)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_document(
    session: AsyncSession,
    doc_id: str,
    firm_id: str,
) -> BuildingCodeDocumentModel | None:
    """Fetch a single document, scoped to firm_id."""
    result = await session.execute(
        select(BuildingCodeDocumentModel)
        .where(BuildingCodeDocumentModel.doc_id == doc_id)
        .where(BuildingCodeDocumentModel.firm_id == firm_id)
    )
    return result.scalar_one_or_none()


async def create_document(
    session: AsyncSession,
    firm_id: str,
    uploaded_by: str,
    jurisdiction: str,
    code_name: str,
    code_version: str,
    s3_key: str,
) -> BuildingCodeDocumentModel:
    """Create a new BuildingCodeDocumentModel after PDF upload."""
    doc = BuildingCodeDocumentModel(
        doc_id=str(uuid.uuid4()),
        firm_id=firm_id,
        jurisdiction=jurisdiction,
        code_name=code_name,
        code_version=code_version,
        uploaded_by=uploaded_by,
        s3_key=s3_key,
        status="uploaded",
    )
    session.add(doc)
    await session.flush()  # populate doc_id in-memory before returning
    return doc


async def update_document_status(
    session: AsyncSession,
    doc_id: str,
    firm_id: str,
    status: str,
    **extra_fields: Any,
) -> BuildingCodeDocumentModel | None:
    """Update status (and any extra fields) on a document."""
    doc = await get_document(session, doc_id, firm_id)
    if doc is None:
        return None
    doc.status = status
    for field, value in extra_fields.items():
        setattr(doc, field, value)
    session.add(doc)
    return doc


# ---------------------------------------------------------------------------
# ExtractedRuleModel — LLM-extracted rules pending review
# ---------------------------------------------------------------------------


async def get_extracted_rules(
    session: AsyncSession,
    doc_id: str,
    approved: bool | None = None,
) -> list[ExtractedRuleModel]:
    """
    Return extracted rules for a document.

    Args:
        approved: None → all; True → approved only; False → rejected only.
                  Use approved=False with reviewer_approved IS NULL for pending
                  (handled by caller using the returned list).
    """
    stmt = (
        select(ExtractedRuleModel)
        .where(ExtractedRuleModel.doc_id == doc_id)
        .order_by(ExtractedRuleModel.source_page, ExtractedRuleModel.extracted_rule_id)
    )
    if approved is not None:
        stmt = stmt.where(ExtractedRuleModel.reviewer_approved == approved)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_extracted_rule(
    session: AsyncSession,
    extracted_rule_id: str,
    doc_id: str,
) -> ExtractedRuleModel | None:
    """Fetch a single extracted rule, scoped to doc_id."""
    result = await session.execute(
        select(ExtractedRuleModel)
        .where(ExtractedRuleModel.extracted_rule_id == extracted_rule_id)
        .where(ExtractedRuleModel.doc_id == doc_id)
    )
    return result.scalar_one_or_none()


async def approve_extracted_rule(
    session: AsyncSession,
    extracted_rule_id: str,
    doc_id: str,
    reviewer_id: str,
    approved: bool,
    notes: str | None = None,
) -> ExtractedRuleModel | None:
    """
    Set reviewer decision on an extracted rule.

    Returns None if the rule is not found.
    """
    rule = await get_extracted_rule(session, extracted_rule_id, doc_id)
    if rule is None:
        return None
    rule.reviewer_approved = approved
    rule.reviewed_by = reviewer_id
    rule.reviewed_at = datetime.now(UTC)
    rule.reviewer_notes = notes
    session.add(rule)
    return rule


async def activate_approved_rules(
    session: AsyncSession,
    doc_id: str,
    firm_id: str,
) -> int:
    """
    Promote all reviewer_approved=True ExtractedRuleModel rows to
    JurisdictionRuleModel.

    Also updates the BuildingCodeDocumentModel.rules_approved count and
    sets its status to "active".

    Returns the number of rules activated.
    """
    doc = await get_document(session, doc_id, firm_id)
    if doc is None:
        raise ValueError(f"Document {doc_id} not found for firm {firm_id}")

    approved_rows = await get_extracted_rules(session, doc_id, approved=True)

    count = 0
    for extracted in approved_rows:
        rule_id = extracted.proposed_rule_id

        # Build a DesignRule to leverage upsert_rule's normalisation logic
        design_rule = DesignRule(
            rule_id=rule_id,
            jurisdiction=extracted.jurisdiction,
            code_version=doc.code_version,
            category=RuleCategory(extracted.category),
            severity=Severity(extracted.severity),
            rule_type=extracted.category,  # default; extracted rules may refine this
            name=extracted.name,
            description=extracted.description,
            source_section=extracted.source_section,
            numeric_value=extracted.numeric_value,
            unit=extracted.unit,
            is_active=True,
        )
        await upsert_rule(session, design_rule, source_doc_id=doc_id)
        count += 1

    # Update document counters and status
    doc.rules_approved = count
    doc.status = "active"
    session.add(doc)

    logger.info(
        "Activated %d rules from document %s (jurisdiction=%s)",
        count, doc_id, doc.jurisdiction,
    )
    return count


# ---------------------------------------------------------------------------
# Helper: ORM model → DesignRule
# ---------------------------------------------------------------------------


def model_to_design_rule(m: JurisdictionRuleModel) -> DesignRule:
    """Convert a JurisdictionRuleModel ORM row to a DesignRule Pydantic object."""
    return DesignRule(
        rule_id=m.rule_id,
        jurisdiction=m.jurisdiction,
        code_version=m.code_version,
        category=RuleCategory(m.category),
        severity=Severity(m.severity),
        rule_type=m.rule_type or "",
        name=m.name,
        description=m.description,
        source_section=m.source_section or "",
        applies_to=list(m.applies_to or []),
        numeric_value=m.numeric_value,
        unit=m.unit,
        reference_rooms=list(m.reference_rooms or []),
        tags=list(m.tags or []),
        embedding_text=m.embedding_text or "",
        is_active=m.is_active,
    )
