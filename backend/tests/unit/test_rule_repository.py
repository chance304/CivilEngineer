"""
Unit tests for the rule repository layer.

Uses AsyncMock / MagicMock to simulate the database session — no real DB required.
Tests focus on query construction, ORM mapping, and business logic in the repo
functions (upsert, activate, supersede, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from civilengineer.db.models import (
    BuildingCodeDocumentModel,
    ExtractedRuleModel,
    JurisdictionRuleModel,
)
from civilengineer.db.repositories import rule_repository
from civilengineer.schemas.rules import DesignRule, RuleCategory, Severity


# ---------------------------------------------------------------------------
# Helpers — build lightweight mock objects
# ---------------------------------------------------------------------------

def _make_rule_model(
    rule_id: str = "NP_KTM_AREA_101",
    jurisdiction: str = "NP-KTM",
    code_version: str = "NBC_2020",
    category: str = "area",
    severity: str = "hard",
    is_active: bool = True,
    superseded_by: str | None = None,
) -> JurisdictionRuleModel:
    m = JurisdictionRuleModel(
        rule_id=rule_id,
        jurisdiction=jurisdiction,
        code_version=code_version,
        category=category,
        severity=severity,
        rule_type="min_area",
        name="Test rule",
        description="A test rule.",
        source_section="NBC §5.1",
        applies_to=["master_bedroom"],
        numeric_value=10.5,
        unit="sqm",
        reference_rooms=[],
        embedding_text="test embedding",
        tags=["residential"],
        is_active=is_active,
        superseded_by=superseded_by,
        effective_from=datetime.now(UTC),
    )
    return m


def _make_design_rule(rule_id: str = "NP_KTM_AREA_101") -> DesignRule:
    return DesignRule(
        rule_id=rule_id,
        jurisdiction="NP-KTM",
        code_version="NBC_2020",
        category=RuleCategory.AREA,
        severity=Severity.HARD,
        rule_type="min_area",
        name="Min master bedroom area",
        description="Master bedroom ≥ 10.5 sqm.",
        source_section="NBC 205:2020, §5.1.2(a)",
        applies_to=["master_bedroom"],
        numeric_value=10.5,
        unit="sqm",
        is_active=True,
    )


def _make_doc(
    doc_id: str = "doc-001",
    firm_id: str = "firm-001",
    jurisdiction: str = "NP-KTM",
    status: str = "review",
) -> BuildingCodeDocumentModel:
    return BuildingCodeDocumentModel(
        doc_id=doc_id,
        firm_id=firm_id,
        jurisdiction=jurisdiction,
        code_name="NBC 205:2020",
        code_version="NBC_2020",
        uploaded_by="user-001",
        s3_key=f"{firm_id}/{doc_id}/nbc.pdf",
        status=status,
        rules_extracted=5,
        rules_approved=0,
    )


def _make_extracted(
    extracted_rule_id: str = "ext-001",
    doc_id: str = "doc-001",
    proposed_rule_id: str = "NP_KTM_AREA_201",
    reviewer_approved: bool | None = None,
) -> ExtractedRuleModel:
    return ExtractedRuleModel(
        extracted_rule_id=extracted_rule_id,
        doc_id=doc_id,
        jurisdiction="NP-KTM",
        proposed_rule_id=proposed_rule_id,
        name="Min bedroom area",
        description="Each bedroom ≥ 9.5 sqm.",
        source_section="§5.1.2(b)",
        source_page=12,
        source_text="The bedroom shall have a minimum area of 9.5 sqm.",
        category="area",
        severity="hard",
        numeric_value=9.5,
        unit="sqm",
        confidence=0.92,
        reviewer_approved=reviewer_approved,
    )


# ---------------------------------------------------------------------------
# Helper: mock session with scalar_one_or_none returning a value
# ---------------------------------------------------------------------------

def _mock_session_returning(value):
    """Return a mock AsyncSession whose execute() yields value via scalar_one_or_none."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = value
    execute_result.scalars.return_value.all.return_value = [value] if value else []
    session.execute = AsyncMock(return_value=execute_result)
    return session


def _mock_session_returning_list(values: list):
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = values
    execute_result.scalar_one_or_none.return_value = values[0] if values else None
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ===========================================================================
# model_to_design_rule
# ===========================================================================

class TestModelToDesignRule:

    def test_converts_all_fields(self):
        m = _make_rule_model()
        rule = rule_repository.model_to_design_rule(m)

        assert rule.rule_id == "NP_KTM_AREA_101"
        assert rule.jurisdiction == "NP-KTM"
        assert rule.code_version == "NBC_2020"
        assert rule.category == RuleCategory.AREA
        assert rule.severity == Severity.HARD
        assert rule.rule_type == "min_area"
        assert rule.name == "Test rule"
        assert rule.numeric_value == 10.5
        assert rule.unit == "sqm"
        assert rule.applies_to == ["master_bedroom"]
        assert rule.is_active is True

    def test_handles_none_lists(self):
        m = _make_rule_model()
        m.applies_to = None  # type: ignore[assignment]
        m.tags = None  # type: ignore[assignment]
        m.reference_rooms = None  # type: ignore[assignment]
        rule = rule_repository.model_to_design_rule(m)
        assert rule.applies_to == []
        assert rule.tags == []
        assert rule.reference_rooms == []

    def test_handles_none_embedding_text(self):
        m = _make_rule_model()
        m.embedding_text = None  # type: ignore[assignment]
        rule = rule_repository.model_to_design_rule(m)
        assert rule.embedding_text == ""


# ===========================================================================
# get_active_rules
# ===========================================================================

class TestGetActiveRules:

    @pytest.mark.asyncio
    async def test_returns_active_rules_for_jurisdiction(self):
        model = _make_rule_model()
        session = _mock_session_returning_list([model])

        rules = await rule_repository.get_active_rules(session, "NP-KTM")
        assert len(rules) == 1
        assert rules[0].rule_id == "NP_KTM_AREA_101"
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rules(self):
        session = _mock_session_returning_list([])
        rules = await rule_repository.get_active_rules(session, "US-CA")
        assert rules == []

    @pytest.mark.asyncio
    async def test_code_version_filter_included(self):
        """Verify code_version filter path executes without error."""
        session = _mock_session_returning_list([])
        rules = await rule_repository.get_active_rules(session, "NP-KTM", code_version="NBC_2020")
        assert rules == []


# ===========================================================================
# get_rule
# ===========================================================================

class TestGetRule:

    @pytest.mark.asyncio
    async def test_returns_rule_when_found(self):
        model = _make_rule_model()
        session = _mock_session_returning(model)
        result = await rule_repository.get_rule(session, "NP_KTM_AREA_101")
        assert result is model

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        session = _mock_session_returning(None)
        result = await rule_repository.get_rule(session, "NONEXISTENT")
        assert result is None


# ===========================================================================
# upsert_rule
# ===========================================================================

class TestUpsertRule:

    @pytest.mark.asyncio
    async def test_inserts_new_rule(self):
        """When no existing row, a new JurisdictionRuleModel is added."""
        session = _mock_session_returning(None)  # get_rule returns None
        design_rule = _make_design_rule()

        result = await rule_repository.upsert_rule(session, design_rule)
        session.add.assert_called_once()
        assert result.rule_id == design_rule.rule_id
        assert result.jurisdiction == "NP-KTM"
        assert result.numeric_value == 10.5

    @pytest.mark.asyncio
    async def test_updates_existing_rule(self):
        """When row exists, its mutable fields are updated in place."""
        existing = _make_rule_model()
        session = _mock_session_returning(existing)

        design_rule = _make_design_rule()
        design_rule = design_rule.model_copy(update={"name": "Updated name", "numeric_value": 11.0})

        result = await rule_repository.upsert_rule(session, design_rule)
        assert result is existing
        assert existing.name == "Updated name"
        assert existing.numeric_value == 11.0
        session.add.assert_called_once_with(existing)

    @pytest.mark.asyncio
    async def test_sets_source_doc_id_on_insert(self):
        session = _mock_session_returning(None)
        design_rule = _make_design_rule()

        result = await rule_repository.upsert_rule(session, design_rule, source_doc_id="doc-999")
        assert result.source_doc_id == "doc-999"


# ===========================================================================
# supersede_rule
# ===========================================================================

class TestSupersedeRule:

    @pytest.mark.asyncio
    async def test_marks_old_rule_superseded(self):
        old = _make_rule_model(rule_id="NP_KTM_AREA_OLD")
        session = _mock_session_returning(old)

        await rule_repository.supersede_rule(session, "NP_KTM_AREA_OLD", "NP_KTM_AREA_NEW")

        assert old.superseded_by == "NP_KTM_AREA_NEW"
        assert old.is_active is False
        session.add.assert_called_once_with(old)

    @pytest.mark.asyncio
    async def test_no_op_when_rule_not_found(self):
        session = _mock_session_returning(None)
        # Should not raise
        await rule_repository.supersede_rule(session, "DOES_NOT_EXIST", "NEW_RULE")
        session.add.assert_not_called()


# ===========================================================================
# get_documents / get_document
# ===========================================================================

class TestDocumentQueries:

    @pytest.mark.asyncio
    async def test_get_documents_returns_list(self):
        doc = _make_doc()
        session = _mock_session_returning_list([doc])

        result = await rule_repository.get_documents(session, "firm-001")
        assert len(result) == 1
        assert result[0].doc_id == "doc-001"

    @pytest.mark.asyncio
    async def test_get_document_scoped_to_firm(self):
        doc = _make_doc()
        session = _mock_session_returning(doc)

        result = await rule_repository.get_document(session, "doc-001", "firm-001")
        assert result is doc

    @pytest.mark.asyncio
    async def test_get_document_returns_none_when_not_found(self):
        session = _mock_session_returning(None)
        result = await rule_repository.get_document(session, "doc-999", "firm-001")
        assert result is None


# ===========================================================================
# approve_extracted_rule
# ===========================================================================

class TestApproveExtractedRule:

    @pytest.mark.asyncio
    async def test_approves_rule(self):
        extracted = _make_extracted()
        session = _mock_session_returning(extracted)

        result = await rule_repository.approve_extracted_rule(
            session,
            extracted_rule_id="ext-001",
            doc_id="doc-001",
            reviewer_id="user-admin",
            approved=True,
            notes="Looks good.",
        )

        assert result is extracted
        assert extracted.reviewer_approved is True
        assert extracted.reviewed_by == "user-admin"
        assert extracted.reviewer_notes == "Looks good."
        assert extracted.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_rejects_rule(self):
        extracted = _make_extracted()
        session = _mock_session_returning(extracted)

        result = await rule_repository.approve_extracted_rule(
            session, "ext-001", "doc-001", "user-admin", False, "Wrong value.",
        )

        assert result.reviewer_approved is False
        assert result.reviewer_notes == "Wrong value."

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        session = _mock_session_returning(None)
        result = await rule_repository.approve_extracted_rule(
            session, "NONEXISTENT", "doc-001", "user-admin", True,
        )
        assert result is None


# ===========================================================================
# activate_approved_rules
# ===========================================================================

class TestActivateApprovedRules:

    @pytest.mark.asyncio
    async def test_activates_approved_rules(self):
        doc = _make_doc(status="review")
        extracted_approved = _make_extracted(reviewer_approved=True)
        extracted_rejected = _make_extracted(
            extracted_rule_id="ext-002",
            proposed_rule_id="NP_KTM_AREA_202",
            reviewer_approved=False,
        )

        # Session returns doc, then the approved-only list for get_extracted_rules
        session = AsyncMock()
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # get_document query
                result.scalar_one_or_none.return_value = doc
            elif call_count == 2:
                # get_extracted_rules(approved=True)
                result.scalars.return_value.all.return_value = [extracted_approved]
            else:
                # get_rule inside upsert_rule — return None so it inserts
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=_execute)

        count = await rule_repository.activate_approved_rules(session, "doc-001", "firm-001")

        assert count == 1
        assert doc.rules_approved == 1
        assert doc.status == "active"

    @pytest.mark.asyncio
    async def test_raises_when_doc_not_found(self):
        session = _mock_session_returning(None)

        with pytest.raises(ValueError, match="not found"):
            await rule_repository.activate_approved_rules(session, "missing-doc", "firm-001")

    @pytest.mark.asyncio
    async def test_zero_count_when_no_approved_rules(self):
        doc = _make_doc()

        session = AsyncMock()
        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = doc
            else:
                result.scalars.return_value.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        session.execute = AsyncMock(side_effect=_execute)

        count = await rule_repository.activate_approved_rules(session, "doc-001", "firm-001")
        assert count == 0
        assert doc.status == "active"
