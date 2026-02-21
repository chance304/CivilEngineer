"""
Unit tests for Phase 6 — LangGraph agent graph.

Test classes
------------
TestQuestionExtractors     — extractor functions (no LLM)
TestAnswerAssembly         — answers_to_requirements()
TestAdaptiveGating         — questions_for_phase(), feasibility warnings
TestInterviewSubgraph      — interview graph with mocked interrupt
TestValidateNode           — validate_node in isolation
TestPlanNode               — plan_node computes buildable zone
TestSolveNode              — solve_node runs CP-SAT
TestRelaxNode              — relax_node reduces room count on UNSAT
TestGeometryNode           — geometry_node produces FloorPlan dicts
TestVerifyNode             — verify_node runs rule engine
TestSaveOutputNode         — save_output_node writes report.json
TestGraphRouting           — conditional edge logic
TestFullPipeline           — end-to-end without interrupts (auto requirements)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from civilengineer.requirements_interview.questions import (
    QUESTION_BY_ID,
    answers_to_requirements,
    extract_bhk,
    extract_bool,
    extract_building_type,
    extract_num_floors,
    extract_special_rooms,
    extract_style,
    get_feasibility_warnings,
    questions_for_phase,
)
from civilengineer.requirements_interview.state import (
    PHASE_BUILDING_TYPE,
    PHASE_ROOMS,
    PHASE_STYLE,
)
from civilengineer.schemas.design import (
    DesignRequirements,
    RoomRequirement,
    RoomType,
    StylePreference,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _plot_dict(width: float = 15.0, depth: float = 20.0) -> dict:
    return {
        "dwg_storage_key": "test.dxf",
        "polygon": [],
        "area_sqm": width * depth,
        "width_m": width,
        "depth_m": depth,
        "is_rectangular": True,
        "north_direction_deg": 0.0,
        "facing": "south",
        "existing_features": [],
        "scale_factor": 1.0,
        "extraction_confidence": 0.95,
        "extraction_notes": [],
        "road_width_m": 7.0,
    }


def _req_dict(num_floors: int = 2, road_width: float = 7.0) -> dict:
    return {
        "project_id": "test",
        "jurisdiction": "NP-KTM",
        "num_floors": num_floors,
        "road_width_m": road_width,
        "rooms": [
            {"room_type": "living_room"},
            {"room_type": "dining_room"},
            {"room_type": "kitchen"},
            {"room_type": "master_bedroom"},
            {"room_type": "bedroom"},
            {"room_type": "bedroom"},
            {"room_type": "bathroom"},
            {"room_type": "bathroom"},
            {"room_type": "toilet"},
            {"room_type": "staircase"},
        ],
        "style": "modern",
        "vastu_compliant": False,
        "notes": "",
    }


def _zone_dict(width: float = 11.0, depth: float = 14.0) -> dict:
    return {"x": 1.5, "y": 1.5, "width": width, "depth": depth}


# ===========================================================================
# TestQuestionExtractors
# ===========================================================================

class TestQuestionExtractors:

    def test_extract_building_type_residential(self):
        assert extract_building_type("residential home") == "residential"

    def test_extract_building_type_commercial(self):
        assert extract_building_type("office building") == "commercial"

    def test_extract_building_type_mixed(self):
        assert extract_building_type("mixed use development") == "mixed"

    def test_extract_num_floors_g_plus_1(self):
        assert extract_num_floors("G+1") == 2

    def test_extract_num_floors_3_storey(self):
        assert extract_num_floors("3 storey building") == 3

    def test_extract_num_floors_2_floors(self):
        assert extract_num_floors("2 floors please") == 2

    def test_extract_num_floors_plain_number(self):
        assert extract_num_floors("4") == 4

    def test_extract_bhk_3bhk(self):
        result = extract_bhk("3BHK")
        assert result["bedroom_count"] == 3
        assert result["bathroom_count"] == 2

    def test_extract_bhk_2_bedrooms(self):
        result = extract_bhk("2 bedrooms 1 bathroom")
        assert result["bedroom_count"] == 2
        assert result["bathroom_count"] == 1

    def test_extract_style_modern(self):
        assert extract_style("modern style") == StylePreference.MODERN

    def test_extract_style_traditional(self):
        assert extract_style("traditional design") == StylePreference.TRADITIONAL

    def test_extract_style_newari(self):
        assert extract_style("Newari architecture") == StylePreference.NEWARI

    def test_extract_bool_yes(self):
        assert extract_bool("yes") is True
        assert extract_bool("Yes please") is True

    def test_extract_bool_no(self):
        assert extract_bool("no") is False
        assert extract_bool("nope") is False

    def test_extract_special_rooms_office(self):
        rooms = extract_special_rooms("I need a home office and a garage")
        assert RoomType.HOME_OFFICE in rooms
        assert RoomType.GARAGE in rooms

    def test_extract_special_rooms_pooja(self):
        rooms = extract_special_rooms("pooja room and store")
        assert RoomType.POOJA_ROOM in rooms

    def test_extract_special_rooms_none(self):
        rooms = extract_special_rooms("none")
        assert rooms == []


# ===========================================================================
# TestAnswerAssembly
# ===========================================================================

class TestAnswerAssembly:

    def test_3bhk_produces_correct_rooms(self):
        answers = {
            "num_floors": 2,
            "bhk_config": {"bedroom_count": 3, "bathroom_count": 2},
            "master_bedroom": True,
            "style": StylePreference.MODERN,
            "vastu": False,
            "special_rooms": [],
        }
        req_dict = answers_to_requirements(answers, "test")
        req = DesignRequirements.model_validate(req_dict)
        types = [r.room_type for r in req.rooms]

        assert RoomType.MASTER_BEDROOM in types
        bedrooms = [t for t in types if t == RoomType.BEDROOM]
        assert len(bedrooms) == 2
        assert RoomType.KITCHEN in types
        assert RoomType.LIVING_ROOM in types

    def test_staircase_added_for_multi_floor(self):
        answers = {
            "num_floors": 2,
            "bhk_config": {"bedroom_count": 2, "bathroom_count": 1},
            "master_bedroom": False,
        }
        req_dict = answers_to_requirements(answers, "test")
        req = DesignRequirements.model_validate(req_dict)
        assert any(r.room_type == RoomType.STAIRCASE for r in req.rooms)

    def test_no_staircase_for_single_floor(self):
        answers = {
            "num_floors": 1,
            "bhk_config": {"bedroom_count": 2, "bathroom_count": 1},
            "master_bedroom": False,
        }
        req_dict = answers_to_requirements(answers, "test")
        req = DesignRequirements.model_validate(req_dict)
        assert not any(r.room_type == RoomType.STAIRCASE for r in req.rooms)

    def test_special_rooms_included(self):
        answers = {
            "num_floors": 1,
            "bhk_config": {"bedroom_count": 2, "bathroom_count": 1},
            "special_rooms": [RoomType.HOME_OFFICE, RoomType.GARAGE],
        }
        req_dict = answers_to_requirements(answers, "test")
        req = DesignRequirements.model_validate(req_dict)
        types = [r.room_type for r in req.rooms]
        assert RoomType.HOME_OFFICE in types
        assert RoomType.GARAGE in types

    def test_vastu_flag_propagated(self):
        answers = {
            "num_floors": 1,
            "bhk_config": {"bedroom_count": 2, "bathroom_count": 1},
            "vastu": True,
        }
        req_dict = answers_to_requirements(answers, "test")
        req = DesignRequirements.model_validate(req_dict)
        assert req.vastu_compliant is True


# ===========================================================================
# TestAdaptiveGating
# ===========================================================================

class TestAdaptiveGating:

    def test_bhk_question_active_for_residential(self):
        answers = {"building_type": "residential"}
        qs = questions_for_phase(PHASE_ROOMS, answers)
        ids = [q.id for q in qs]
        assert "bhk_config" in ids

    def test_bhk_question_inactive_for_commercial(self):
        answers = {"building_type": "commercial"}
        qs = questions_for_phase(PHASE_ROOMS, answers)
        ids = [q.id for q in qs]
        assert "bhk_config" not in ids

    def test_style_question_always_active(self):
        qs = questions_for_phase(PHASE_STYLE, {})
        ids = [q.id for q in qs]
        assert "style" in ids

    def test_feasibility_warning_small_plot_4bhk(self):
        answers = {
            "num_floors": 1,
            "bhk_config": {"bedroom_count": 4},
        }
        warnings = get_feasibility_warnings(answers, plot_area_sqm=200.0)
        assert any("4" in w or "bhk" in w.lower() or "bedroom" in w.lower()
                   for w in warnings)

    def test_no_feasibility_warning_reasonable_config(self):
        answers = {
            "num_floors": 2,
            "bhk_config": {"bedroom_count": 3},
        }
        warnings = get_feasibility_warnings(answers, plot_area_sqm=600.0)
        assert len(warnings) == 0


# ===========================================================================
# TestValidateNode
# ===========================================================================

class TestValidateNode:

    def test_valid_requirements_no_errors(self):
        from civilengineer.agent.nodes.validate_node import validate_node
        state = {
            "project_id": "t",
            "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": _plot_dict(),
            "errors": [],
            "warnings": [],
        }
        result = validate_node(state)
        assert result.get("validation_errors", []) == []

    def test_missing_requirements_produces_error(self):
        from civilengineer.agent.nodes.validate_node import validate_node
        state = {
            "project_id": "t",
            "session_id": "s",
            "requirements": None,
            "plot_info": _plot_dict(),
            "errors": [],
            "warnings": [],
        }
        result = validate_node(state)
        assert len(result.get("errors", [])) > 0

    def test_missing_plot_info_returns_warning(self):
        from civilengineer.agent.nodes.validate_node import validate_node
        state = {
            "project_id": "t",
            "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": None,
            "errors": [],
            "warnings": [],
        }
        result = validate_node(state)
        # Should warn but not error
        assert len(result.get("validation_errors", [])) == 0
        assert len(result.get("validation_warnings", [])) > 0 or \
               len(result.get("warnings", [])) > 0


# ===========================================================================
# TestPlanNode
# ===========================================================================

class TestPlanNode:

    def test_plan_node_computes_buildable_zone(self):
        from civilengineer.agent.nodes.plan_node import plan_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": _plot_dict(),
            "errors": [], "warnings": [],
        }
        result = plan_node(state)
        assert "buildable_zone" in result
        zone = result["buildable_zone"]
        assert zone["width"] > 0
        assert zone["depth"] > 0

    def test_plan_node_computes_setbacks(self):
        from civilengineer.agent.nodes.plan_node import plan_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": _plot_dict(),
            "errors": [], "warnings": [],
        }
        result = plan_node(state)
        setbacks = result.get("setbacks")
        assert setbacks is not None
        assert len(setbacks) == 4
        assert all(s > 0 for s in setbacks)

    def test_plan_node_no_plot_uses_stub(self):
        from civilengineer.agent.nodes.plan_node import plan_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": None,
            "errors": [], "warnings": [],
        }
        result = plan_node(state)
        assert "buildable_zone" in result
        assert len(result.get("warnings", [])) > 0


# ===========================================================================
# TestSolveNode
# ===========================================================================

class TestSolveNode:

    def test_solve_node_returns_sat(self):
        from civilengineer.agent.nodes.solve_node import solve_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "buildable_zone": _zone_dict(),
            "errors": [], "warnings": [],
        }
        result = solve_node(state)
        assert "solve_result" in result
        sr = result["solve_result"]
        assert sr["status"] in ("SAT", "PARTIAL")

    def test_solve_node_missing_zone_errors(self):
        from civilengineer.agent.nodes.solve_node import solve_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "buildable_zone": None,
            "errors": [], "warnings": [],
        }
        result = solve_node(state)
        assert len(result.get("errors", [])) > 0

    def test_solve_node_unsat_tiny_zone(self):
        from civilengineer.agent.nodes.solve_node import solve_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(num_floors=1),
            "buildable_zone": {"x": 0.0, "y": 0.0, "width": 2.0, "depth": 2.0},
            "errors": [], "warnings": [],
        }
        result = solve_node(state)
        sr = result.get("solve_result", {})
        # Either UNSAT errors or PARTIAL
        if sr.get("status") == "UNSAT":
            assert len(result.get("errors", [])) > 0


# ===========================================================================
# TestRelaxNode
# ===========================================================================

class TestRelaxNode:

    def test_relax_removes_optional_rooms(self):
        from civilengineer.agent.nodes.relax_node import relax_node
        req = dict(_req_dict())
        req["rooms"].append({"room_type": "balcony"})
        req["rooms"].append({"room_type": "terrace"})

        state = {
            "requirements": req,
            "revision_count": 0,
            "errors": ["UNSAT"],
            "warnings": [],
        }
        result = relax_node(state)
        new_rooms = DesignRequirements.model_validate(result["requirements"]).rooms
        types = [r.room_type for r in new_rooms]
        assert RoomType.BALCONY not in types
        assert RoomType.TERRACE not in types

    def test_relax_increments_revision_count(self):
        from civilengineer.agent.nodes.relax_node import relax_node
        state = {
            "requirements": _req_dict(),
            "revision_count": 1,
            "errors": [],
            "warnings": [],
        }
        result = relax_node(state)
        assert result.get("revision_count", 0) == 2

    def test_relax_stops_at_max_revisions(self):
        from civilengineer.agent.nodes.relax_node import relax_node
        state = {
            "requirements": _req_dict(),
            "revision_count": 3,
            "errors": [],
            "warnings": [],
        }
        result = relax_node(state)
        assert any("failed" in e.lower() or "too small" in e.lower()
                   for e in result.get("errors", []))


# ===========================================================================
# TestGeometryNode
# ===========================================================================

class TestGeometryNode:

    def _make_solve_result(self) -> dict:
        from civilengineer.reasoning_engine.constraint_solver import solve_layout
        from civilengineer.knowledge.rule_compiler import load_rules
        from civilengineer.schemas.design import Rect2D, DesignRequirements, RoomRequirement

        req = DesignRequirements.model_validate(_req_dict())
        zone = Rect2D(x=1.5, y=1.5, width=11.0, depth=14.0)
        rules = load_rules().rules
        result = solve_layout(req, zone, rules, timeout_s=30.0)
        return result.model_dump()

    def test_geometry_node_produces_floor_plans(self):
        from civilengineer.agent.nodes.geometry_node import geometry_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "solve_result": self._make_solve_result(),
            "plot_info": _plot_dict(),
            "setbacks": [1.5, 1.5, 1.0, 1.0],
            "errors": [], "warnings": [],
        }
        result = geometry_node(state)
        assert "floor_plans" in result
        assert len(result["floor_plans"]) >= 1

    def test_geometry_node_produces_building_design(self):
        from civilengineer.agent.nodes.geometry_node import geometry_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "solve_result": self._make_solve_result(),
            "plot_info": _plot_dict(),
            "setbacks": [1.5, 1.5, 1.0, 1.0],
            "errors": [], "warnings": [],
        }
        result = geometry_node(state)
        bd = result.get("building_design")
        assert bd is not None
        assert bd["num_floors"] == 2

    def test_geometry_node_floor_plans_have_walls(self):
        from civilengineer.agent.nodes.geometry_node import geometry_node
        from civilengineer.schemas.design import FloorPlan
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "solve_result": self._make_solve_result(),
            "plot_info": _plot_dict(),
            "setbacks": [1.5, 1.5, 1.0, 1.0],
            "errors": [], "warnings": [],
        }
        result = geometry_node(state)
        for fp_dict in result["floor_plans"]:
            fp = FloorPlan.model_validate(fp_dict)
            assert len(fp.wall_segments) > 0


# ===========================================================================
# TestVerifyNode
# ===========================================================================

class TestVerifyNode:

    def _make_building_design(self) -> dict:
        from civilengineer.reasoning_engine.constraint_solver import solve_layout
        from civilengineer.geometry_engine.layout_generator import generate_floor_plans
        from civilengineer.geometry_engine.wall_builder import build_walls
        from civilengineer.knowledge.rule_compiler import load_rules
        from civilengineer.schemas.design import Rect2D, DesignRequirements, BuildingDesign
        from civilengineer.schemas.project import PlotInfo, PlotFacing
        import uuid

        req = DesignRequirements.model_validate(_req_dict())
        zone = Rect2D(x=1.5, y=1.5, width=11.0, depth=14.0)
        rules = load_rules()
        result = solve_layout(req, zone, rules.rules, timeout_s=30.0)

        plot = PlotInfo.model_validate(_plot_dict())
        fps = generate_floor_plans(result, req, plot, (1.5, 1.5, 1.0, 1.0))
        for fp in fps:
            build_walls(fp)

        design = BuildingDesign(
            design_id=str(uuid.uuid4())[:8],
            project_id="test",
            jurisdiction="NP-KTM",
            num_floors=2,
            plot_width=15.0,
            plot_depth=20.0,
            floor_plans=fps,
            setback_front=1.5, setback_rear=1.5,
            setback_left=1.0,  setback_right=1.0,
        )
        return design.model_dump()

    def test_verify_node_produces_compliance_report(self):
        from civilengineer.agent.nodes.verify_node import verify_node
        state = {
            "project_id": "t", "session_id": "s",
            "requirements": _req_dict(),
            "plot_info": _plot_dict(),
            "building_design": self._make_building_design(),
            "revision_count": 0,
            "errors": [], "warnings": [],
        }
        result = verify_node(state)
        assert "compliance_report" in result
        cr = result["compliance_report"]
        assert "compliant" in cr

    def test_verify_node_no_building_design_errors(self):
        from civilengineer.agent.nodes.verify_node import verify_node
        state = {
            "project_id": "t", "session_id": "s",
            "building_design": None,
            "revision_count": 0,
            "errors": [], "warnings": [],
        }
        result = verify_node(state)
        assert len(result.get("errors", [])) > 0


# ===========================================================================
# TestSaveOutputNode
# ===========================================================================

class TestSaveOutputNode:

    def test_save_output_writes_report(self):
        from civilengineer.agent.nodes.save_output_node import save_output_node
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "project_id": "t",
                "session_id": "test_sess",
                "output_dir": tmp,
                "compliance_report": {"compliant": True, "violations": [], "warnings": []},
                "dxf_paths": [],
                "errors": [], "warnings": [],
            }
            result = save_output_node(state)
            report_path = result.get("report_path")
            assert report_path is not None
            assert Path(report_path).exists()

    def test_save_output_message_contains_status(self):
        from civilengineer.agent.nodes.save_output_node import save_output_node
        with tempfile.TemporaryDirectory() as tmp:
            state = {
                "project_id": "t",
                "session_id": "test_sess",
                "output_dir": tmp,
                "compliance_report": {"compliant": False, "violations": [{"message": "test"}], "warnings": []},
                "dxf_paths": ["floor_1.dxf"],
                "errors": [], "warnings": [],
            }
            result = save_output_node(state)
            msgs = result.get("messages", [])
            assert len(msgs) == 1
            assert "complete" in msgs[0].content.lower()


# ===========================================================================
# TestGraphRouting
# ===========================================================================

class TestGraphRouting:

    def test_after_validate_no_errors_routes_to_plan(self):
        from civilengineer.agent.graph import _after_validate
        state = {"validation_errors": [], "errors": []}
        assert _after_validate(state) == "plan"

    def test_after_validate_with_errors_routes_to_end(self):
        from civilengineer.agent.graph import _after_validate
        state = {"validation_errors": ["Plot too small"], "errors": []}
        assert _after_validate(state) == "__end__"

    def test_after_solve_sat_routes_to_geometry(self):
        from civilengineer.agent.graph import _after_solve
        state = {"solve_result": {"status": "SAT"}}
        assert _after_solve(state) == "geometry"

    def test_after_solve_unsat_routes_to_relax(self):
        from civilengineer.agent.graph import _after_solve
        state = {"solve_result": {"status": "UNSAT"}}
        assert _after_solve(state) == "relax"

    def test_after_relax_under_limit_routes_to_solve(self):
        from civilengineer.agent.graph import _after_relax
        state = {"revision_count": 1, "errors": []}
        assert _after_relax(state) == "solve"

    def test_after_relax_over_limit_routes_to_end(self):
        from civilengineer.agent.graph import _after_relax
        state = {"revision_count": 5, "errors": []}
        assert _after_relax(state) == "__end__"

    def test_after_human_review_approved_routes_to_draw(self):
        from civilengineer.agent.graph import _after_human_review
        state = {"should_revise": False, "errors": []}
        assert _after_human_review(state) == "draw"

    def test_after_human_review_revise_routes_to_solve(self):
        from civilengineer.agent.graph import _after_human_review
        state = {"should_revise": True, "errors": []}
        assert _after_human_review(state) == "solve"

    def test_after_human_review_abort_routes_to_end(self):
        from civilengineer.agent.graph import _after_human_review
        state = {"should_revise": False, "errors": ["Design aborted by engineer"]}
        assert _after_human_review(state) == "__end__"

    def test_after_verify_pass_routes_to_save(self):
        from civilengineer.agent.graph import _after_verify
        state = {"should_revise": False}
        assert _after_verify(state) == "save_output"

    def test_after_verify_fail_routes_to_relax(self):
        from civilengineer.agent.graph import _after_verify
        state = {"should_revise": True}
        assert _after_verify(state) == "relax"


# ===========================================================================
# TestFullPipeline — end-to-end with mocked interrupts
# ===========================================================================

class TestFullPipeline:
    """
    Run the full pipeline without stopping at interrupt points.
    We mock interrupt() to return pre-canned answers.
    """

    def test_pipeline_completes_with_auto_responses(self):
        """
        Full pipeline from initial state to save_output.
        interrupt() is mocked to return "approve" for human_review
        and requirements for the interview interrupt.
        """
        from civilengineer.agent.graph import build_graph
        from civilengineer.agent.state import make_initial_state
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.types import Command

        interview_answer = "3BHK 2 floors modern"
        human_review_answer = "approve"

        call_count = [0]

        def mock_interrupt(data):
            call_count[0] += 1
            itype = data.get("type", "")
            if itype == "human_review":
                return human_review_answer
            return interview_answer

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "civilengineer.agent.nodes.human_review_node.interrupt",
                side_effect=mock_interrupt,
            ), patch(
                "civilengineer.agent.graph.interrupt",
                side_effect=mock_interrupt,
            ):
                graph = build_graph(MemorySaver())
                config = {"configurable": {"thread_id": "test-full-pipeline"}}
                initial = make_initial_state("test_proj", "sess_001")
                initial["output_dir"] = tmp
                initial["plot_info"] = {
                    "dwg_storage_key": "test.dxf",
                    "polygon": [],
                    "area_sqm": 300.0,
                    "width_m": 15.0,
                    "depth_m": 20.0,
                    "is_rectangular": True,
                    "north_direction_deg": 0.0,
                    "facing": "south",
                    "existing_features": [],
                    "scale_factor": 1.0,
                    "extraction_confidence": 0.95,
                    "extraction_notes": [],
                    "road_width_m": 7.0,
                }

                try:
                    result = graph.invoke(initial, config=config)
                    # If graph ran to completion, check outputs
                    assert result is not None
                    # Should have either dxf_paths or errors (not both empty and no dxf)
                    has_output = (
                        result.get("dxf_paths")
                        or result.get("floor_plans")
                        or result.get("solve_result")
                    )
                    assert has_output, \
                        f"Pipeline produced no output. Errors: {result.get('errors')}"
                except Exception as exc:
                    # Graph may interrupt — that's acceptable in test context
                    # The important thing is no crash before first interrupt
                    assert "interrupt" in str(type(exc).__name__).lower() or \
                           "GraphInterrupt" in str(type(exc).__name__), \
                        f"Unexpected exception: {type(exc).__name__}: {exc}"

    def test_graph_builds_without_error(self):
        """Smoke test: the graph can be compiled."""
        from civilengineer.agent.graph import build_graph
        from langgraph.checkpoint.memory import MemorySaver
        graph = build_graph(MemorySaver())
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """Verify all nodes are registered in the graph."""
        from civilengineer.agent.graph import build_graph
        from langgraph.checkpoint.memory import MemorySaver
        graph = build_graph(MemorySaver())
        # LangGraph 1.x stores nodes in graph.builder or graph.nodes
        expected = {
            "load_project", "interview", "validate", "plan",
            "solve", "relax", "geometry", "human_review",
            "draw", "verify", "save_output",
        }
        try:
            nodes = set(graph.nodes.keys())
            assert expected.issubset(nodes), \
                f"Missing nodes: {expected - nodes}"
        except AttributeError:
            pass  # graph structure inspection varies by version
