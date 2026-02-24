"""
Unit tests for client approval logic.

Tests the request/response models and the validation helpers directly
(not the DB or HTTP layer — those are integration tests).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civilengineer.api.routers.design import (
    ClientApproveRequest,
    ClientApprovalResponse,
)
from civilengineer.db.models import ClientApprovalModel


# ---------------------------------------------------------------------------
# ClientApproveRequest validation
# ---------------------------------------------------------------------------


class TestClientApproveRequest:
    def test_approved_action_valid(self):
        req = ClientApproveRequest(action="approved")
        assert req.action == "approved"
        assert req.notes == ""

    def test_revision_requested_valid(self):
        req = ClientApproveRequest(action="revision_requested", notes="Please widen the staircase.")
        assert req.action == "revision_requested"
        assert req.notes == "Please widen the staircase."

    def test_notes_optional(self):
        req = ClientApproveRequest(action="approved")
        assert req.notes == ""

    def test_unknown_action_still_parses(self):
        # Validation of action values happens in the endpoint, not the model
        req = ClientApproveRequest(action="other_value")
        assert req.action == "other_value"

    def test_notes_with_action(self):
        req = ClientApproveRequest(action="approved", notes="Looks great!")
        assert req.notes == "Looks great!"


# ---------------------------------------------------------------------------
# ClientApprovalResponse
# ---------------------------------------------------------------------------


class TestClientApprovalResponse:
    def test_no_approval(self):
        resp = ClientApprovalResponse(session_id="s1", has_approval=False)
        assert resp.has_approval is False
        assert resp.action is None
        assert resp.notes is None
        assert resp.submitted_by is None
        assert resp.submitted_at is None

    def test_with_approval(self):
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        resp = ClientApprovalResponse(
            session_id="s1",
            has_approval=True,
            action="approved",
            notes=None,
            submitted_by="user-123",
            submitted_at=now,
        )
        assert resp.has_approval is True
        assert resp.action == "approved"
        assert resp.submitted_by == "user-123"

    def test_revision_response(self):
        from datetime import UTC, datetime

        resp = ClientApprovalResponse(
            session_id="s1",
            has_approval=True,
            action="revision_requested",
            notes="Increase bedroom size",
            submitted_by="u1",
            submitted_at=datetime.now(UTC),
        )
        assert resp.action == "revision_requested"
        assert resp.notes == "Increase bedroom size"


# ---------------------------------------------------------------------------
# ClientApprovalModel (DB model)
# ---------------------------------------------------------------------------


class TestClientApprovalModel:
    def test_model_creates(self):
        from datetime import UTC, datetime

        model = ClientApprovalModel(
            project_id="p1",
            session_id="s1",
            firm_id="f1",
            submitted_by="user-1",
            submitted_at=datetime.now(UTC),
            action="approved",
            notes="",
        )
        assert model.action == "approved"
        assert model.approval_id is not None   # default_factory generates UUID

    def test_default_notes_is_empty(self):
        from datetime import UTC, datetime

        model = ClientApprovalModel(
            project_id="p1",
            session_id="s1",
            firm_id="f1",
            submitted_by="u1",
            submitted_at=datetime.now(UTC),
            action="approved",
        )
        assert model.notes == ""

    def test_approval_id_is_uuid_string(self):
        from datetime import UTC, datetime
        import re

        model = ClientApprovalModel(
            project_id="p1",
            session_id="s1",
            firm_id="f1",
            submitted_by="u1",
            submitted_at=datetime.now(UTC),
            action="revision_requested",
            notes="Fix the layout",
        )
        # UUIDs are hex strings (with or without hyphens)
        assert re.match(r"[0-9a-f-]{32,36}", model.approval_id)

    def test_two_models_get_different_ids(self):
        from datetime import UTC, datetime

        m1 = ClientApprovalModel(
            project_id="p1", session_id="s1", firm_id="f1",
            submitted_by="u1", submitted_at=datetime.now(UTC), action="approved",
        )
        m2 = ClientApprovalModel(
            project_id="p1", session_id="s1", firm_id="f1",
            submitted_by="u1", submitted_at=datetime.now(UTC), action="approved",
        )
        assert m1.approval_id != m2.approval_id


# ---------------------------------------------------------------------------
# Action validation logic (mirrors endpoint guard)
# ---------------------------------------------------------------------------


class TestActionValidation:
    """Reproduce the endpoint's validation rules as pure logic tests."""

    VALID_ACTIONS = {"approved", "revision_requested"}

    def _validate(self, action: str, notes: str) -> str | None:
        """Returns an error string, or None if valid."""
        if action not in self.VALID_ACTIONS:
            return f"invalid action: {action!r}"
        if action == "revision_requested" and not notes.strip():
            return "notes required for revision_requested"
        return None

    def test_approved_no_notes_ok(self):
        assert self._validate("approved", "") is None

    def test_approved_with_notes_ok(self):
        assert self._validate("approved", "Looks good!") is None

    def test_revision_with_notes_ok(self):
        assert self._validate("revision_requested", "Add a balcony") is None

    def test_revision_empty_notes_fails(self):
        assert self._validate("revision_requested", "") is not None

    def test_revision_whitespace_notes_fails(self):
        assert self._validate("revision_requested", "   ") is not None

    def test_unknown_action_fails(self):
        assert self._validate("abort", "") is not None

    def test_blank_action_fails(self):
        assert self._validate("", "") is not None
