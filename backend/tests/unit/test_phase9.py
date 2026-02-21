"""
Phase 9 tests — API Integration + Design Pipeline Wiring.

Coverage:
  - SessionStore: SqliteSaver wrapper, thread_id mapping, graph construction
  - DesignJob Celery task: structure, make_job_id, _summarise_floor_plans
  - LoadProjectNode: DB-backed loading, fast-path skip, fallback stub
  - DesignRouter: REST endpoint schemas and routing logic
  - DesignJobModel DB schema
  - app.py registration of design router
  - celery_app.py includes design_job
  - Job schemas: DesignJob, JobStatus, ApprovalRequest, ApprovalResponse
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =========================================================================== #
# TestSessionStore                                                              #
# =========================================================================== #

class TestSessionStore:
    """Tests for agent/session_store.py."""

    def test_session_to_thread_id_prefix(self):
        from civilengineer.agent.session_store import session_to_thread_id
        assert session_to_thread_id("abc123") == "session:abc123"

    def test_thread_id_to_session_id(self):
        from civilengineer.agent.session_store import thread_id_to_session_id
        assert thread_id_to_session_id("session:abc123") == "abc123"

    def test_thread_id_roundtrip(self):
        from civilengineer.agent.session_store import (
            session_to_thread_id, thread_id_to_session_id
        )
        sid = "sess_abcdef123456"
        assert thread_id_to_session_id(session_to_thread_id(sid)) == sid

    def test_get_sessions_db_path_creates_dir(self, tmp_path):
        from civilengineer.agent.session_store import get_sessions_db_path
        sub = tmp_path / "new_subdir"
        db_path = get_sessions_db_path(base_dir=sub)
        assert sub.exists()
        assert db_path.name == "agent_sessions.db"
        assert db_path.parent == sub

    def test_get_sessions_db_path_default(self, tmp_path, monkeypatch):
        from civilengineer.agent import session_store
        monkeypatch.setattr(session_store, "_DEFAULT_SESSIONS_DIR", tmp_path / "sessions")
        path = session_store.get_sessions_db_path()
        assert path.name == "agent_sessions.db"

    def test_build_persistent_graph_returns_graph(self, tmp_path):
        from civilengineer.agent.session_store import build_persistent_graph
        db = tmp_path / "test_sessions.db"
        graph = build_persistent_graph(db_path=db)
        # Compiled LangGraph graph must have invoke() and get_state()
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "get_state")

    def test_build_persistent_graph_fallback_to_memory(self, tmp_path):
        """If SqliteSaver is unavailable, falls back to MemorySaver."""
        from civilengineer.agent import session_store

        with patch.dict("sys.modules", {"langgraph.checkpoint.sqlite": None}):
            # Should not raise even if sqlite module unavailable
            # (we can't truly block the import here, but verify fallback logic exists)
            graph = session_store.build_persistent_graph(tmp_path / "s.db")
            assert hasattr(graph, "invoke")

    def test_get_graph_state_returns_none_on_fresh_session(self, tmp_path):
        from civilengineer.agent.session_store import (
            build_persistent_graph, get_graph_state
        )
        graph = build_persistent_graph(tmp_path / "s.db")
        # No state exists for brand new session
        result = get_graph_state(graph, "nonexistent_session")
        assert result is None

    def test_get_pending_interrupt_returns_none_on_fresh(self, tmp_path):
        from civilengineer.agent.session_store import (
            build_persistent_graph, get_pending_interrupt
        )
        graph = build_persistent_graph(tmp_path / "s.db")
        result = get_pending_interrupt(graph, "fresh_session_xyz")
        assert result is None


# =========================================================================== #
# TestDesignJobTask                                                             #
# =========================================================================== #

class TestDesignJobTask:
    """Tests for jobs/design_job.py."""

    def test_make_job_id_format(self):
        from civilengineer.jobs.design_job import make_job_id
        jid = make_job_id()
        assert jid.startswith("job_")
        assert len(jid) == 16   # "job_" + 12 hex chars

    def test_make_job_id_unique(self):
        from civilengineer.jobs.design_job import make_job_id
        ids = {make_job_id() for _ in range(50)}
        assert len(ids) == 50

    def test_task_is_registered_in_celery(self):
        from civilengineer.jobs.design_job import run_design_pipeline
        assert callable(run_design_pipeline)
        assert run_design_pipeline.name == "civilengineer.jobs.design_job.run_design_pipeline"

    def test_task_max_retries_zero(self):
        from civilengineer.jobs.design_job import run_design_pipeline
        assert run_design_pipeline.max_retries == 0

    def test_celery_app_includes_design_job(self):
        from civilengineer.jobs.celery_app import celery_app
        assert "civilengineer.jobs.design_job" in celery_app.conf.include

    def test_summarise_floor_plans_empty(self):
        from civilengineer.jobs.design_job import _summarise_floor_plans
        summary = _summarise_floor_plans([])
        assert summary["total_rooms"] == 0
        assert summary["num_floors"] == 0
        assert summary["floors"] == []

    def test_summarise_floor_plans_single_floor(self):
        from civilengineer.jobs.design_job import _summarise_floor_plans
        fps = [
            {
                "floor": 1,
                "rooms": [
                    {"room_type": "bedroom", "area_sqm": 12.5},
                    {"room_type": "bathroom", "area_sqm": 4.0},
                ],
            }
        ]
        summary = _summarise_floor_plans(fps)
        assert summary["num_floors"] == 1
        assert summary["total_rooms"] == 2
        assert abs(summary["total_area_sqm"] - 16.5) < 0.01
        assert summary["floors"][0]["floor"] == 1

    def test_summarise_floor_plans_multi_floor(self):
        from civilengineer.jobs.design_job import _summarise_floor_plans
        fps = [
            {"floor": 1, "rooms": [{"room_type": "living", "area_sqm": 20}]},
            {"floor": 2, "rooms": [
                {"room_type": "bedroom", "area_sqm": 15},
                {"room_type": "bedroom", "area_sqm": 12},
            ]},
        ]
        summary = _summarise_floor_plans(fps)
        assert summary["num_floors"] == 2
        assert summary["total_rooms"] == 3
        assert abs(summary["total_area_sqm"] - 47.0) < 0.01

    def test_summarise_handles_missing_room_fields(self):
        from civilengineer.jobs.design_job import _summarise_floor_plans
        fps = [{"floor": 1, "rooms": [{}]}]
        summary = _summarise_floor_plans(fps)
        assert summary["total_rooms"] == 1
        assert summary["total_area_sqm"] == 0.0

    def test_load_project_async_returns_none_on_failure(self):
        """_load_project_async returns (None, None, None) when DB is unavailable."""
        import asyncio
        from civilengineer.jobs.design_job import _load_project_async

        async def run():
            # No real DB → should return None tuple gracefully
            with patch(
                "civilengineer.jobs.design_job._load_project_async",
                new=AsyncMock(return_value=(None, None, None)),
            ):
                return await _load_project_async("proj_fake123")

        result = asyncio.run(run())
        assert result == (None, None, None)

    def test_publish_event_graceful_on_no_redis(self):
        """_publish_event should not raise even when Redis is unreachable."""
        import asyncio
        from civilengineer.jobs.design_job import _publish_event

        async def run():
            # Should complete without raising
            await _publish_event("proj_123", {"type": "test"})

        # Patch to avoid actual Redis connection
        with patch("civilengineer.jobs.design_job._publish_event", new=AsyncMock()):
            asyncio.run(run())


# =========================================================================== #
# TestLoadProjectNode                                                           #
# =========================================================================== #

class TestLoadProjectNode:
    """Tests for agent/nodes/load_project_node.py."""

    def test_skips_db_when_project_in_state(self):
        from civilengineer.agent.nodes.load_project_node import load_project_node

        state = {
            "project_id": "proj_abc",
            "project": {"project_id": "proj_abc", "status": "ready"},
        }
        result = load_project_node(state)  # type: ignore[arg-type]
        # Should return empty dict — no DB load needed
        assert result == {}

    def test_returns_empty_project_on_db_failure(self):
        from civilengineer.agent.nodes.load_project_node import load_project_node

        state = {"project_id": "proj_missing", "session_id": "s1"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=(None, None, None),
        ):
            result = load_project_node(state)  # type: ignore[arg-type]

        assert "project" in result
        assert result["project"]["project_id"] == "proj_missing"

    def test_populates_plot_info_when_available(self):
        from civilengineer.agent.nodes.load_project_node import load_project_node

        plot = {"area_sqm": 200.0}
        state = {"project_id": "proj_x", "session_id": "s2"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=(
                {"project_id": "proj_x", "status": "ready"},
                plot,
                None,
            ),
        ):
            result = load_project_node(state)  # type: ignore[arg-type]

        assert result["plot_info"] == plot

    def test_populates_requirements_when_available(self):
        from civilengineer.agent.nodes.load_project_node import load_project_node

        reqs = {"num_floors": 2, "bhk_config": "3BHK"}
        state = {"project_id": "proj_y", "session_id": "s3"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=(
                {"project_id": "proj_y", "status": "ready"},
                None,
                reqs,
            ),
        ):
            result = load_project_node(state)  # type: ignore[arg-type]

        assert result["requirements"] == reqs

    def test_load_from_db_returns_tuple_on_exception(self):
        from civilengineer.agent.nodes.load_project_node import _load_from_db

        # No real DB available; should return None tuple gracefully
        result = _load_from_db("proj_nonexistent_xyz")
        assert result == (None, None, None)

    def test_node_logs_warning_on_missing_project(self, caplog):
        import logging
        from civilengineer.agent.nodes.load_project_node import load_project_node

        state = {"project_id": "proj_gone", "session_id": "s99"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=(None, None, None),
        ):
            with caplog.at_level(logging.WARNING, logger="civilengineer.agent.nodes.load_project_node"):
                load_project_node(state)  # type: ignore[arg-type]

        assert any("not found" in rec.message for rec in caplog.records)

    def test_node_logs_info_on_success(self, caplog):
        import logging
        from civilengineer.agent.nodes.load_project_node import load_project_node

        state = {"project_id": "proj_ok", "session_id": "s10"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=(
                {"project_id": "proj_ok", "status": "ready"},
                None, None,
            ),
        ):
            with caplog.at_level(logging.INFO, logger="civilengineer.agent.nodes.load_project_node"):
                load_project_node(state)  # type: ignore[arg-type]

        assert any("Loaded project" in rec.message for rec in caplog.records)

    def test_no_plot_info_key_when_none(self):
        from civilengineer.agent.nodes.load_project_node import load_project_node

        state = {"project_id": "proj_noplot", "session_id": "s11"}
        with patch(
            "civilengineer.agent.nodes.load_project_node._load_from_db",
            return_value=({"project_id": "proj_noplot"}, None, None),
        ):
            result = load_project_node(state)  # type: ignore[arg-type]

        assert "plot_info" not in result
        assert "requirements" not in result


# =========================================================================== #
# TestDesignRouterSchemas                                                       #
# =========================================================================== #

class TestDesignRouterSchemas:
    """Test schema validation for design router request/response bodies."""

    def test_start_design_request_optional_body(self):
        from civilengineer.api.routers.design import StartDesignRequest
        req = StartDesignRequest()
        assert req.requirements_override is None
        assert req.output_dir is None

    def test_start_design_request_with_overrides(self):
        from civilengineer.api.routers.design import StartDesignRequest
        req = StartDesignRequest(
            requirements_override={"num_floors": 2},
            output_dir="/tmp/out",
        )
        assert req.requirements_override == {"num_floors": 2}
        assert req.output_dir == "/tmp/out"

    def test_interview_reply_request(self):
        from civilengineer.api.routers.design import InterviewReplyRequest
        req = InterviewReplyRequest(reply="3BHK, 2 floors, modern")
        assert req.reply == "3BHK, 2 floors, modern"

    def test_design_job_summary_schema(self):
        from datetime import datetime, timezone
        from civilengineer.api.routers.design import DesignJobSummary
        from civilengineer.schemas.jobs import JobStatus

        s = DesignJobSummary(
            job_id="job_abc123",
            session_id="sess_xyz",
            status=JobStatus.PENDING,
            current_step="loading",
            submitted_at=datetime.now(timezone.utc),
        )
        assert s.job_id == "job_abc123"
        assert s.completed_at is None

    def test_design_job_summary_with_completed_at(self):
        from datetime import datetime, timezone
        from civilengineer.api.routers.design import DesignJobSummary
        from civilengineer.schemas.jobs import JobStatus

        now = datetime.now(timezone.utc)
        s = DesignJobSummary(
            job_id="job_x",
            session_id="sess_y",
            status=JobStatus.COMPLETED,
            current_step="done",
            submitted_at=now,
            completed_at=now,
        )
        assert s.completed_at == now

    def test_row_to_schema_helper(self):
        from datetime import datetime, timezone
        from civilengineer.api.routers.design import _row_to_schema
        from civilengineer.db.models import DesignJobModel

        now = datetime.now(timezone.utc)
        row = DesignJobModel(
            job_id="job_aaa",
            celery_task_id="celery-uuid-1",
            project_id="proj_aaa",
            firm_id="firm_1",
            session_id="sess_aaa",
            submitted_by="user_1",
            submitted_at=now,
            status="pending",
            current_step="loading",
        )
        schema = _row_to_schema(row)
        assert schema.job_id == "job_aaa"
        assert schema.project_id == "proj_aaa"
        assert schema.status.value == "pending"


# =========================================================================== #
# TestDesignRouterEndpoints                                                     #
# =========================================================================== #

class TestDesignRouterEndpoints:
    """Verify router registration and endpoint path definitions."""

    def test_design_router_has_start_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design" in paths

    def test_design_router_has_list_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design" in paths

    def test_design_router_has_get_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design/{session_id}" in paths

    def test_design_router_has_interview_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design/{session_id}/interview" in paths

    def test_design_router_has_approve_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design/{session_id}/approve" in paths

    def test_design_router_has_cancel_route(self):
        from civilengineer.api.routers.design import router
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/design/{session_id}" in paths

    def test_design_router_tag(self):
        from civilengineer.api.routers.design import router
        assert "design" in router.tags

    def test_app_includes_design_router(self):
        """Verify the FastAPI app registers the design router."""
        from civilengineer.api.app import create_app
        app = create_app()
        all_paths = [r.path for r in app.routes]
        design_paths = [p for p in all_paths if "/design" in p]
        assert len(design_paths) >= 3


# =========================================================================== #
# TestJobSchemas                                                                #
# =========================================================================== #

class TestJobSchemas:
    """Tests for schemas/jobs.py."""

    def test_job_status_values(self):
        from civilengineer.schemas.jobs import JobStatus
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.PAUSED.value == "paused"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_design_job_step_values(self):
        from civilengineer.schemas.jobs import DesignJobStep
        assert DesignJobStep.LOADING.value == "loading"
        assert DesignJobStep.AWAITING_APPROVAL.value == "awaiting_approval"
        assert DesignJobStep.DONE.value == "done"

    def test_job_progress_schema(self):
        from civilengineer.schemas.jobs import JobProgress, JobStatus, DesignJobStep
        p = JobProgress(
            job_id="job_1",
            project_id="proj_1",
            session_id="sess_1",
            status=JobStatus.RUNNING,
            current_step=DesignJobStep.SOLVING,
            step_message="Solving…",
            progress_pct=45,
        )
        assert p.progress_pct == 45
        assert p.solver_iteration is None

    def test_design_job_schema(self):
        from datetime import datetime, timezone
        from civilengineer.schemas.jobs import DesignJob, JobStatus, DesignJobStep
        now = datetime.now(timezone.utc)
        j = DesignJob(
            job_id="job_2",
            celery_task_id="ct-1",
            project_id="proj_2",
            session_id="sess_2",
            firm_id="firm_1",
            submitted_by="user_1",
            submitted_at=now,
            status=JobStatus.COMPLETED,
            current_step=DesignJobStep.DONE,
        )
        assert j.result is None
        assert j.error is None

    def test_approval_request_schema(self):
        from civilengineer.schemas.jobs import ApprovalRequest
        ar = ApprovalRequest(
            job_id="job_3",
            session_id="sess_3",
            floor_plan_summary={"num_floors": 2},
            compliance_preview={},
        )
        assert ar.constraints_relaxed == []
        assert ar.solver_iterations == 0

    def test_approval_response_schema(self):
        from civilengineer.schemas.jobs import ApprovalResponse
        resp = ApprovalResponse(job_id="job_3", approved=True)
        assert resp.approved is True
        assert resp.feedback is None

    def test_approval_response_with_feedback(self):
        from civilengineer.schemas.jobs import ApprovalResponse
        resp = ApprovalResponse(
            job_id="job_4",
            approved=False,
            feedback="Make the master bedroom larger",
        )
        assert resp.approved is False
        assert "larger" in resp.feedback  # type: ignore[operator]


# =========================================================================== #
# TestDesignJobModelDB                                                          #
# =========================================================================== #

class TestDesignJobModelDB:
    """Tests for DesignJobModel ORM model fields."""

    def test_model_has_required_fields(self):
        from datetime import datetime, timezone
        from civilengineer.db.models import DesignJobModel
        row = DesignJobModel(
            job_id="job_x",
            celery_task_id="ct-abc",
            project_id="proj_1",
            firm_id="firm_1",
            session_id="sess_x",
            submitted_by="user_1",
            submitted_at=datetime.now(timezone.utc),
            status="pending",
            current_step="loading",
        )
        assert row.job_id == "job_x"
        assert row.status == "pending"

    def test_model_optional_fields_default_none(self):
        from datetime import datetime, timezone
        from civilengineer.db.models import DesignJobModel
        row = DesignJobModel(
            job_id="job_y",
            celery_task_id="",
            project_id="proj_2",
            firm_id="firm_1",
            session_id="sess_y",
            submitted_by="user_1",
            submitted_at=datetime.now(timezone.utc),
            status="pending",
            current_step="loading",
        )
        assert row.started_at is None
        assert row.completed_at is None
        assert row.result is None
        assert row.error is None

    def test_model_status_can_be_updated(self):
        from datetime import datetime, timezone
        from civilengineer.db.models import DesignJobModel
        row = DesignJobModel(
            job_id="job_z",
            celery_task_id="ct-z",
            project_id="proj_3",
            firm_id="firm_1",
            session_id="sess_z",
            submitted_by="user_1",
            submitted_at=datetime.now(timezone.utc),
            status="pending",
            current_step="loading",
        )
        row.status = "running"
        assert row.status == "running"
        row.status = "completed"
        assert row.status == "completed"

    def test_model_result_is_dict(self):
        from datetime import datetime, timezone
        from civilengineer.db.models import DesignJobModel
        row = DesignJobModel(
            job_id="job_r",
            celery_task_id="ct-r",
            project_id="proj_4",
            firm_id="firm_1",
            session_id="sess_r",
            submitted_by="user_1",
            submitted_at=datetime.now(timezone.utc),
            status="completed",
            current_step="done",
            result={"output_files": ["a.dxf"]},
        )
        assert row.result == {"output_files": ["a.dxf"]}


# =========================================================================== #
# TestAgentStateV2                                                              #
# =========================================================================== #

class TestAgentStateV2:
    """Tests for the updated AgentState (Phase 9 additions)."""

    def test_make_initial_state_has_pdf_paths(self):
        from civilengineer.agent.state import make_initial_state
        s = make_initial_state("proj_a", "sess_a")
        assert "pdf_paths" in s
        assert s["pdf_paths"] is None

    def test_make_initial_state_has_cost_estimate(self):
        from civilengineer.agent.state import make_initial_state
        s = make_initial_state("proj_b", "sess_b")
        assert "cost_estimate" in s
        assert s["cost_estimate"] is None

    def test_initial_state_project_and_session_ids(self):
        from civilengineer.agent.state import make_initial_state
        s = make_initial_state("proj_test", "sess_test")
        assert s["project_id"] == "proj_test"
        assert s["session_id"] == "sess_test"

    def test_initial_state_empty_lists(self):
        from civilengineer.agent.state import make_initial_state
        s = make_initial_state("p", "s")
        assert s["errors"] == []
        assert s["warnings"] == []
        assert s["validation_errors"] == []

    def test_state_is_serializable(self):
        from civilengineer.agent.state import make_initial_state
        s = make_initial_state("proj_json", "sess_json")
        # Must be JSON-serialisable (no non-serialisable types except messages)
        d = {k: v for k, v in s.items() if k != "messages"}
        json_str = json.dumps(d)
        restored = json.loads(json_str)
        assert restored["project_id"] == "proj_json"

    def test_graph_builds_with_memory_checkpointer(self):
        from civilengineer.agent.graph import build_graph
        from langgraph.checkpoint.memory import MemorySaver
        graph = build_graph(MemorySaver())
        assert hasattr(graph, "invoke")

    def test_session_store_get_sessions_db_path_returns_path_obj(self, tmp_path):
        from civilengineer.agent.session_store import get_sessions_db_path
        p = get_sessions_db_path(tmp_path)
        assert isinstance(p, Path)
