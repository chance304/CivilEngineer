"""
Unit tests for the decisions repository layer.

Uses AsyncMock / MagicMock to simulate the database session — no real DB required.
Tests cover write functions, query routing in persist_decision_events, and read
functions (query construction).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from civilengineer.db.repositories import decisions_repository as repo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_session():
    """Async DB session mock."""
    session = AsyncMock()
    session.add = MagicMock()  # add() is sync in SQLAlchemy
    return session


_PROJECT = "proj_abc123"
_FIRM = "firm_xyz"
_JOB = "job_def456"
_SESSION = "sess_ghi789"
_USER = "user_aaa111"


# ---------------------------------------------------------------------------
# log_project_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_project_change_adds_row(mock_session):
    row = await repo.log_project_change(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        changed_by=_USER,
        field_name="name",
        old_value={"value": "Old Name"},
        new_value={"value": "New Name"},
    )
    mock_session.add.assert_called_once_with(row)
    assert row.project_id == _PROJECT
    assert row.field_name == "name"
    assert row.change_source == "api"


@pytest.mark.asyncio
async def test_log_project_change_scalar_values_wrapped(mock_session):
    row = await repo.log_project_change(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        changed_by=_USER,
        field_name="name",
        old_value="Old",
        new_value="New",
    )
    assert row.old_value == {"value": "Old"}
    assert row.new_value == {"value": "New"}


# ---------------------------------------------------------------------------
# write_requirements_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_requirements_version_increments(mock_session):
    # Simulate 2 existing versions
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    mock_session.execute = AsyncMock(return_value=count_result)

    row = await repo.write_requirements_version(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        requirements={"bhk": 3},
    )
    assert row.version_number == 3
    assert row.requirements == {"bhk": 3}
    assert row.job_id == _JOB
    mock_session.add.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_write_requirements_version_first_version(mock_session):
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(return_value=count_result)

    row = await repo.write_requirements_version(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        requirements={},
    )
    assert row.version_number == 1


# ---------------------------------------------------------------------------
# write_design_approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_design_approval_stores_decision(mock_session):
    row = await repo.write_design_approval(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        approved_by=_USER,
        decision="approve",
        feedback_text="Looks good!",
        revision_count=1,
    )
    mock_session.add.assert_called_once_with(row)
    assert row.decision == "approve"
    assert row.approved_by == _USER
    assert row.feedback_text == "Looks good!"
    assert row.revision_count == 1
    assert row.approval_type == "floor_plan"


@pytest.mark.asyncio
async def test_write_design_approval_revise(mock_session):
    row = await repo.write_design_approval(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        approved_by=_USER,
        decision="revise",
        feedback_text="Add a bathroom",
    )
    assert row.decision == "revise"


# ---------------------------------------------------------------------------
# write_compliance_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_compliance_report_pass(mock_session):
    compliance = {
        "compliant": True,
        "violations": [],
        "warnings": [{"message": "Minor issue"}],
        "advisories": [],
    }
    row = await repo.write_compliance_report(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        compliance_report=compliance,
        report_path="/output/compliance_report.json",
    )
    mock_session.add.assert_called_once_with(row)
    assert row.is_compliant is True
    assert row.violation_count == 0
    assert row.warning_count == 1
    assert row.report_path == "/output/compliance_report.json"


@pytest.mark.asyncio
async def test_write_compliance_report_fail(mock_session):
    compliance = {
        "compliant": False,
        "violations": [{"message": "Room too small"}, {"message": "Missing setback"}],
        "warnings": [],
        "advisories": [],
    }
    row = await repo.write_compliance_report(
        mock_session,
        project_id=_PROJECT,
        firm_id=_FIRM,
        job_id=_JOB,
        session_id=_SESSION,
        compliance_report=compliance,
    )
    assert row.is_compliant is False
    assert row.violation_count == 2


# ---------------------------------------------------------------------------
# persist_decision_events — routing logic
# ---------------------------------------------------------------------------


def _make_event(node: str, etype: str, data: dict, iteration: int = 0) -> dict:
    return {
        "node": node,
        "type": etype,
        "iteration": iteration,
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": data,
    }


@pytest.mark.asyncio
async def test_persist_events_solve_goes_to_solver_iteration(mock_session):
    events = [
        _make_event("solve", "solver_run", {
            "status": "SAT",
            "placed_count": 5,
            "unplaced_count": 0,
            "solver_time_s": 1.2,
            "warnings": [],
        }),
    ]
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
    # Should have added a SolverIterationLogModel row
    assert mock_session.add.call_count == 1
    added_row = mock_session.add.call_args[0][0]
    from civilengineer.db.models import SolverIterationLogModel
    assert isinstance(added_row, SolverIterationLogModel)
    assert added_row.solver_status == "SAT"
    assert added_row.placed_room_count == 5


@pytest.mark.asyncio
async def test_persist_events_relax_goes_to_solver_iteration(mock_session):
    events = [
        _make_event("relax", "relaxation_applied", {
            "status": "UNSAT",
            "placed_count": 0,
            "unplaced_count": 3,
            "solver_time_s": 0.0,
            "relaxation_type": "remove_optional",
            "rooms_removed": ["balcony"],
            "warnings": ["Removed balcony"],
        }),
    ]
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
    assert mock_session.add.call_count == 1
    added_row = mock_session.add.call_args[0][0]
    from civilengineer.db.models import SolverIterationLogModel
    assert isinstance(added_row, SolverIterationLogModel)
    assert added_row.relaxation_type == "remove_optional"
    assert added_row.rooms_removed == ["balcony"]


@pytest.mark.asyncio
async def test_persist_events_cad_goes_to_elevation_decision(mock_session):
    events = [
        _make_event("draw", "cad_generated", {
            "dxf_paths": ["/out/floor_1.dxf"],
            "pdf_paths": ["/out/design.pdf"],
            "num_floors": 2,
            "roof_type": "flat",
            "facade_material": "standard",
            "floor_heights": [3.0, 3.0],
        }),
    ]
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
    assert mock_session.add.call_count == 1
    added_row = mock_session.add.call_args[0][0]
    from civilengineer.db.models import ElevationDecisionModel
    assert isinstance(added_row, ElevationDecisionModel)
    assert added_row.num_floors == 2
    assert added_row.roof_type == "flat"
    assert "/out/floor_1.dxf" in added_row.output_paths


@pytest.mark.asyncio
async def test_persist_events_generic_goes_to_decision_log(mock_session):
    events = [
        _make_event("validate", "validation_result", {
            "passed": True,
            "errors": [],
            "warnings": [],
        }),
        _make_event("geometry", "geometry_generated", {
            "floor_count": 2,
            "total_rooms": 8,
            "room_types": ["master_bedroom", "bedroom"],
            "wall_segments": 40,
        }),
    ]
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
    assert mock_session.add.call_count == 2
    for add_call in mock_session.add.call_args_list:
        row = add_call[0][0]
        from civilengineer.db.models import DesignDecisionLogModel
        assert isinstance(row, DesignDecisionLogModel)


@pytest.mark.asyncio
async def test_persist_events_mixed_routing(mock_session):
    """Test that a mix of events routes each to its correct table."""
    events = [
        _make_event("validate", "validation_result", {"passed": True, "errors": [], "warnings": []}),
        _make_event("solve", "solver_run", {"status": "SAT", "placed_count": 5, "unplaced_count": 0,
                                            "solver_time_s": 2.0, "warnings": []}),
        _make_event("draw", "cad_generated", {"dxf_paths": [], "pdf_paths": [], "num_floors": 1,
                                              "roof_type": "", "facade_material": "", "floor_heights": []}),
    ]
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
    # 3 rows added: 1 DesignDecisionLog, 1 SolverIteration, 1 ElevationDecision
    assert mock_session.add.call_count == 3

    from civilengineer.db.models import (
        DesignDecisionLogModel,
        ElevationDecisionModel,
        SolverIterationLogModel,
    )
    types = {type(c[0][0]).__name__ for c in mock_session.add.call_args_list}
    assert "DesignDecisionLogModel" in types
    assert "SolverIterationLogModel" in types
    assert "ElevationDecisionModel" in types


@pytest.mark.asyncio
async def test_persist_events_empty_list(mock_session):
    """Empty events list → no DB calls."""
    await repo.persist_decision_events(
        mock_session, [], _PROJECT, _JOB, _SESSION, _FIRM
    )
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_persist_events_bad_event_skipped(mock_session):
    """Malformed event dict should be skipped without crashing."""
    events = [
        {"node": "solve", "type": "solver_run"},  # missing 'data' key
        _make_event("validate", "validation_result", {"passed": True, "errors": [], "warnings": []}),
    ]
    # Should not raise
    await repo.persist_decision_events(
        mock_session, events, _PROJECT, _JOB, _SESSION, _FIRM
    )
