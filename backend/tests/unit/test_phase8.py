"""
Unit tests for Phase 8 — Professional Output + Hardening.

Test classes:
  TestCostEstimator        (12) — room rates, total, breakdown, material grades
  TestCostEstimateModel     (6) — CostEstimate model helpers
  TestSetbackDB            (12) — city lookup, road categories, aliases, fallback
  TestVastuScoring         (12) — zone classification, scoring, violations
  TestVastuOptimizer        (8) — position swapping, dimension compatibility
  TestDXFExporter           (8) — combined DXF, site plan, floor index
  TestPDFExporter           (6) — PDF generation, cover, room schedule
  TestDrawNodeEnhanced      (8) — PDF paths in state, cost estimate in state
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

import pytest

from civilengineer.schemas.design import (
    BuildingDesign,
    Door,
    DoorSwing,
    FloorPlan,
    Rect2D,
    RoomLayout,
    RoomRequirement,
    RoomType,
    WallFace,
    Window,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _room(
    room_type: RoomType,
    x: float, y: float, w: float, d: float,
    floor: int = 1,
    name: Optional[str] = None,
) -> RoomLayout:
    return RoomLayout(
        room_id=str(uuid.uuid4()),
        room_type=room_type,
        name=name or room_type.value,
        floor=floor,
        bounds=Rect2D(x=x, y=y, width=w, depth=d),
    )


def _floor_plan(rooms: list[RoomLayout], floor: int = 1) -> FloorPlan:
    return FloorPlan(
        floor=floor,
        buildable_zone=Rect2D(x=0, y=0, width=13, depth=17),
        rooms=rooms,
    )


def _building(floor_plans: list[FloorPlan]) -> BuildingDesign:
    return BuildingDesign(
        design_id="d1",
        project_id="p1",
        num_floors=len(floor_plans),
        plot_width=15.0,
        plot_depth=20.0,
        floor_plans=floor_plans,
    )


def _simple_building() -> BuildingDesign:
    """3BHK 2-floor building for testing."""
    f1_rooms = [
        _room(RoomType.LIVING_ROOM,  0, 0, 5, 4, floor=1),
        _room(RoomType.KITCHEN,      5, 0, 3, 4, floor=1),
        _room(RoomType.DINING_ROOM,  0, 4, 4, 3, floor=1),
        _room(RoomType.BATHROOM,     8, 0, 2, 2, floor=1),
        _room(RoomType.STAIRCASE,    8, 2, 2, 4, floor=1),
    ]
    f2_rooms = [
        _room(RoomType.MASTER_BEDROOM, 0, 0, 4, 4, floor=2),
        _room(RoomType.BEDROOM,        4, 0, 3, 4, floor=2),
        _room(RoomType.BEDROOM,        7, 0, 3, 4, floor=2),
        _room(RoomType.BATHROOM,       0, 4, 2, 2, floor=2),
        _room(RoomType.STAIRCASE,      8, 2, 2, 4, floor=2),
    ]
    return _building([_floor_plan(f1_rooms, 1), _floor_plan(f2_rooms, 2)])


# ---------------------------------------------------------------------------
# Cost Estimator Tests
# ---------------------------------------------------------------------------


class TestCostEstimator:
    def test_basic_grade_returns_estimate(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("basic").estimate(b)
        assert est.total_cost_inr > 0

    def test_premium_more_than_basic(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        basic   = CostEstimator("basic").estimate(b)
        premium = CostEstimator("premium").estimate(b)
        assert premium.total_cost_inr > basic.total_cost_inr

    def test_standard_between_basic_and_premium(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        basic    = CostEstimator("basic").estimate(b)
        standard = CostEstimator("standard").estimate(b)
        premium  = CostEstimator("premium").estimate(b)
        assert basic.total_cost_inr < standard.total_cost_inr < premium.total_cost_inr

    def test_total_equals_components(self):
        """total = structure + finish + MEP + contingency."""
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        expected = est.structure_cost + est.finish_cost + est.mep_cost + est.contingency_cost
        assert abs(est.total_cost_inr - expected) < 1.0   # rounding tolerance

    def test_cost_per_sqm_computed(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        assert est.cost_per_sqm_inr > 0
        expected = est.total_cost_inr / est.total_area_sqm
        assert abs(est.cost_per_sqm_inr - expected) < 1.0

    def test_type_breakdown_keys_match_room_types(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        room_types_in_building = {
            r.room_type.value
            for fp in b.floor_plans for r in fp.rooms
        }
        assert set(est.type_breakdown.keys()) == room_types_in_building

    def test_room_breakdown_length(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        total_rooms = sum(len(fp.rooms) for fp in b.floor_plans)
        assert len(est.room_breakdown) == total_rooms

    def test_kitchen_higher_finish_than_bedroom(self):
        """Kitchen has a higher finish rate than a same-size bedroom."""
        from civilengineer.output_layer.cost_estimator import CostEstimator
        kitchen_b = _building([_floor_plan([_room(RoomType.KITCHEN, 0, 0, 3, 3)])])
        bedroom_b = _building([_floor_plan([_room(RoomType.BEDROOM, 0, 0, 3, 3)])])
        k_est = CostEstimator("standard").estimate(kitchen_b)
        b_est = CostEstimator("standard").estimate(bedroom_b)
        assert k_est.finish_cost > b_est.finish_cost

    def test_single_room_estimate(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _building([_floor_plan([_room(RoomType.LIVING_ROOM, 0, 0, 5, 5)])])
        est = CostEstimator("standard").estimate(b)
        assert est.total_area_sqm == pytest.approx(25.0, rel=0.01)

    def test_invalid_grade_raises(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        with pytest.raises(ValueError, match="material_grade"):
            CostEstimator("gold")  # type: ignore[arg-type]

    def test_mep_scales_with_structure(self):
        """MEP should be a fixed fraction of structure cost (0.18 for standard)."""
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        expected_mep = est.structure_cost * 0.18
        assert abs(est.mep_cost - expected_mep) < 1.0

    def test_contingency_is_5_percent(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        subtotal = est.structure_cost + est.finish_cost + est.mep_cost
        expected_contingency = subtotal * 0.05
        assert abs(est.contingency_cost - expected_contingency) < 1.0


class TestCostEstimateModel:
    def test_formatted_total_crore(self):
        from civilengineer.output_layer.cost_estimator import CostEstimate
        est = CostEstimate(
            project_id="p", design_id="d", material_grade="standard",
            total_area_sqm=200, structure_cost=0, finish_cost=0,
            mep_cost=0, contingency_cost=0,
            total_cost_inr=1_50_00_000,   # 1.5 crore
            cost_per_sqm_inr=75_000,
            room_breakdown=[], type_breakdown={},
        )
        text = est.formatted_total()
        assert "Cr" in text

    def test_formatted_total_lakh(self):
        from civilengineer.output_layer.cost_estimator import CostEstimate
        est = CostEstimate(
            project_id="p", design_id="d", material_grade="basic",
            total_area_sqm=50, structure_cost=0, finish_cost=0,
            mep_cost=0, contingency_cost=0,
            total_cost_inr=45_00_000,   # 45 lakh
            cost_per_sqm_inr=90_000,
            room_breakdown=[], type_breakdown={},
        )
        text = est.formatted_total()
        assert "L" in text

    def test_project_id_preserved(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        b.project_id = "proj-xyz"
        est = CostEstimator("basic").estimate(b)
        assert est.project_id == "proj-xyz"

    def test_design_id_preserved(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        b.design_id = "design-abc"
        est = CostEstimator("premium").estimate(b)
        assert est.design_id == "design-abc"

    def test_material_grade_recorded(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("premium").estimate(b)
        assert est.material_grade == "premium"

    def test_total_area_matches_rooms(self):
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        manual_area = sum(r.bounds.area for fp in b.floor_plans for r in fp.rooms)
        assert abs(est.total_area_sqm - manual_area) < 0.05


# ---------------------------------------------------------------------------
# Setback DB Tests
# ---------------------------------------------------------------------------


class TestSetbackDB:
    def test_kathmandu_narrow_road(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        front, rear, left, right = db.get_setbacks("Kathmandu", road_width_m=4.0)
        assert front == pytest.approx(1.5)

    def test_kathmandu_collector_road(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        front, _, _, _ = db.get_setbacks("Kathmandu", road_width_m=9.0)
        assert front == pytest.approx(2.0)

    def test_pokhara_local_road(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        front, _, _, _ = db.get_setbacks("Pokhara", road_width_m=7.0)
        assert front == pytest.approx(2.0)

    def test_lalitpur_alias(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        # "Patan" is an alias for Lalitpur
        patan = db.get_setbacks("Patan", road_width_m=7.0)
        lal   = db.get_setbacks("Lalitpur", road_width_m=7.0)
        assert patan == lal

    def test_case_insensitive(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        lower = db.get_setbacks("kathmandu", road_width_m=5.0)
        upper = db.get_setbacks("KATHMANDU", road_width_m=5.0)
        assert lower == upper

    def test_unknown_city_falls_back_to_nepal(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        # City not in DB — should return Nepal generic, not crash
        result = db.get_setbacks("Birgunj", road_width_m=7.0)
        assert len(result) == 4
        assert all(v > 0 for v in result)

    def test_no_road_width_uses_unknown_category(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        result = db.get_setbacks("Kathmandu", road_width_m=None)
        assert len(result) == 4

    def test_road_category_narrow(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        assert db.road_category(4.0) == "narrow"

    def test_road_category_local(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        assert db.road_category(7.0) == "local"

    def test_road_category_collector(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        assert db.road_category(10.0) == "collector"

    def test_road_category_arterial(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        assert db.road_category(15.0) == "arterial"

    def test_supported_cities_includes_ktm(self):
        from civilengineer.knowledge.setback_db import SetbackDB
        db = SetbackDB()
        assert "NP-KTM" in db.supported_cities()


# ---------------------------------------------------------------------------
# Vastu Scoring Tests
# ---------------------------------------------------------------------------


def _placed_room(rt: RoomType, x: float, y: float, w: float, d: float) -> object:
    """Create a PlacedRoom-like object for Vastu tests."""
    from civilengineer.reasoning_engine.constraint_solver import PlacedRoom
    return PlacedRoom(
        room_req=RoomRequirement(room_type=rt),
        floor=1,
        x=x, y=y, width=w, depth=d,
    )


class TestVastuScoring:
    ZONE = Rect2D(x=0, y=0, width=13, depth=17)

    def test_kitchen_in_se_score_1(self):
        """Kitchen centred in SE quadrant → score 1.0."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        # SE quadrant: x > 6.5, y < 8.5
        kitchen = _placed_room(RoomType.KITCHEN, 8, 0, 3, 3)
        result = score_vastu([kitchen], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)

    def test_kitchen_in_nw_score_0(self):
        """Kitchen in NW quadrant → violation and score 0."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        kitchen = _placed_room(RoomType.KITCHEN, 0, 10, 3, 3)
        result = score_vastu([kitchen], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(0.0)
        assert len(result.violations) == 1

    def test_master_bed_in_sw_score_1(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        master = _placed_room(RoomType.MASTER_BEDROOM, 0, 0, 4, 4)
        result = score_vastu([master], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)

    def test_unconstrained_room_always_1(self):
        """Living room is not in _VASTU_CONSTRAINED → always score 1.0."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        living = _placed_room(RoomType.LIVING_ROOM, 0, 12, 5, 4)  # NW quadrant
        result = score_vastu([living], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)
        assert len(result.violations) == 0

    def test_empty_rooms_score_1(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        result = score_vastu([], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)

    def test_multiple_violations_averaged(self):
        """2 violations out of 2 constrained rooms → score 0.0."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        # Both in wrong quadrant
        kitchen = _placed_room(RoomType.KITCHEN, 0, 10, 3, 3)  # NW, should be SE
        master  = _placed_room(RoomType.MASTER_BEDROOM, 8, 10, 4, 4)  # NE, should be SW
        result = score_vastu([kitchen, master], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(0.0)
        assert len(result.violations) == 2

    def test_partial_compliance(self):
        """1 compliant + 1 violation → score 0.5."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        kitchen = _placed_room(RoomType.KITCHEN, 8, 0, 3, 3)   # SE ✓
        master  = _placed_room(RoomType.MASTER_BEDROOM, 8, 10, 4, 4)  # NE ✗
        result = score_vastu([kitchen, master], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(0.5)

    def test_north_facing_rotation(self):
        """For north-facing plot the same position produces a different Vastu score."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        # Kitchen at lower-right (SE for south-facing plot)
        kitchen_s = _placed_room(RoomType.KITCHEN, 8, 0, 3, 3)
        s_score = score_vastu([kitchen_s], self.ZONE, facing="south")
        n_score = score_vastu([kitchen_s], self.ZONE, facing="north")
        # South-facing: kitchen at SE → score 1.0 (correct zone)
        # North-facing: same position maps to NW (mirrored) → violation → score differs
        assert s_score.overall_score != n_score.overall_score

    def test_pooja_in_ne_no_violation(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        pooja = _placed_room(RoomType.POOJA_ROOM, 8, 10, 2, 2)  # NE quadrant
        result = score_vastu([pooja], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)

    def test_bathroom_in_nw_no_violation(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        bath = _placed_room(RoomType.BATHROOM, 0, 10, 2, 2)  # NW
        result = score_vastu([bath], self.ZONE, facing="south")
        assert result.overall_score == pytest.approx(1.0)

    def test_room_results_count_matches_inputs(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        rooms = [
            _placed_room(RoomType.KITCHEN, 8, 0, 3, 3),
            _placed_room(RoomType.LIVING_ROOM, 0, 0, 5, 4),
            _placed_room(RoomType.BEDROOM, 0, 4, 3, 3),
        ]
        result = score_vastu(rooms, self.ZONE)
        assert len(result.room_results) == 3

    def test_violations_list_contains_zone_info(self):
        from civilengineer.reasoning_engine.vastu_solver import score_vastu
        kitchen = _placed_room(RoomType.KITCHEN, 0, 10, 3, 3)  # NW, wrong
        result = score_vastu([kitchen], self.ZONE)
        assert len(result.violations) == 1
        assert "SE" in result.violations[0]   # expected zone mentioned


# ---------------------------------------------------------------------------
# Vastu Optimizer Tests
# ---------------------------------------------------------------------------


class TestVastuOptimizer:
    ZONE = Rect2D(x=0, y=0, width=13, depth=17)

    def test_compatible_same_size_rooms(self):
        """Two rooms with identical dimensions → compatible."""
        from civilengineer.reasoning_engine.vastu_solver import _dimensions_compatible
        a = _placed_room(RoomType.KITCHEN,  0, 0, 3, 3)
        b = _placed_room(RoomType.BEDROOM,  5, 0, 3, 3)
        assert _dimensions_compatible(a, b)

    def test_incompatible_very_different_sizes(self):
        from civilengineer.reasoning_engine.vastu_solver import _dimensions_compatible
        a = _placed_room(RoomType.KITCHEN,  0, 0, 3, 3)
        b = _placed_room(RoomType.BEDROOM, 10, 0, 8, 8)  # too different
        assert not _dimensions_compatible(a, b)

    def test_swap_positions(self):
        from civilengineer.reasoning_engine.vastu_solver import _swap_positions
        a = _placed_room(RoomType.KITCHEN,  2, 0, 3, 3)
        b = _placed_room(RoomType.BEDROOM,  8, 5, 3, 3)
        new_a, new_b = _swap_positions(a, b)
        assert new_a.x == 8 and new_a.y == 5
        assert new_b.x == 2 and new_b.y == 0

    def test_swap_does_not_modify_originals(self):
        from civilengineer.reasoning_engine.vastu_solver import _swap_positions
        a = _placed_room(RoomType.KITCHEN, 2, 0, 3, 3)
        b = _placed_room(RoomType.BEDROOM, 8, 5, 3, 3)
        _swap_positions(a, b)
        assert a.x == 2 and b.x == 8  # originals unchanged

    def test_optimize_returns_same_count(self):
        from civilengineer.reasoning_engine.vastu_solver import optimize_vastu
        rooms = [
            _placed_room(RoomType.KITCHEN,       0, 10, 3, 3),
            _placed_room(RoomType.MASTER_BEDROOM, 8, 10, 4, 4),
        ]
        result = optimize_vastu(rooms, self.ZONE, max_swaps=0)
        assert len(result) == len(rooms)

    def test_optimize_correct_rooms_no_improvement_needed(self):
        """Already-correct placement → no swaps needed, score stays 1.0."""
        from civilengineer.reasoning_engine.vastu_solver import score_vastu, optimize_vastu
        kitchen = _placed_room(RoomType.KITCHEN,       8, 0,  3, 3)  # SE ✓
        master  = _placed_room(RoomType.MASTER_BEDROOM, 0, 0,  3, 3)  # SW ✓
        before = score_vastu([kitchen, master], self.ZONE).overall_score
        optimized = optimize_vastu([kitchen, master], self.ZONE)
        after = score_vastu(optimized, self.ZONE).overall_score
        assert after >= before

    def test_optimize_max_swaps_limit(self):
        """max_swaps=0 → no swaps performed."""
        from civilengineer.reasoning_engine.vastu_solver import optimize_vastu
        kitchen = _placed_room(RoomType.KITCHEN,        0, 10, 3, 3)
        master  = _placed_room(RoomType.MASTER_BEDROOM, 10, 10, 3, 3)
        original_positions = [(kitchen.x, kitchen.y), (master.x, master.y)]
        result = optimize_vastu([kitchen, master], self.ZONE, max_swaps=0)
        result_positions = [(r.x, r.y) for r in result]
        assert result_positions == original_positions

    def test_unconstrained_rooms_unchanged(self):
        """Living room (unconstrained) position is not changed by optimizer."""
        from civilengineer.reasoning_engine.vastu_solver import optimize_vastu
        living  = _placed_room(RoomType.LIVING_ROOM, 5, 5, 5, 4)
        kitchen = _placed_room(RoomType.KITCHEN,     0, 10, 3, 3)
        result = optimize_vastu([living, kitchen], self.ZONE)
        living_result = next(r for r in result if r.room_req.room_type == RoomType.LIVING_ROOM)
        assert living_result.x == living.x and living_result.y == living.y


# ---------------------------------------------------------------------------
# DXF Exporter Tests
# ---------------------------------------------------------------------------


class TestDXFExporter:
    def test_export_combined_creates_file(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        exporter = DXFExporter()
        path = exporter.export_combined(b, tmp_path)
        assert path.exists()
        assert path.suffix == ".dxf"

    def test_export_site_plan_creates_file(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        exporter = DXFExporter()
        path = exporter.export_site_plan(b, None, None, tmp_path)
        assert path.exists()

    def test_export_site_plan_with_setbacks(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        path = DXFExporter().export_site_plan(
            b, {"area_sqm": 300}, (1.5, 1.5, 1.0, 1.0), tmp_path
        )
        assert path.exists()

    def test_export_floor_index_creates_file(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        dxf_paths = [str(tmp_path / "floor_1.dxf"), str(tmp_path / "floor_2.dxf")]
        path = DXFExporter().export_floor_index(b, dxf_paths, tmp_path)
        assert path.exists()

    def test_combined_dxf_is_valid(self, tmp_path):
        """Combined DXF can be read back by ezdxf without errors."""
        import ezdxf  # noqa: PLC0415
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        path = DXFExporter().export_combined(b, tmp_path)
        doc = ezdxf.readfile(str(path))
        assert doc is not None

    def test_custom_combined_filename(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        b = _simple_building()
        path = DXFExporter().export_combined(b, tmp_path, filename="my_combined.dxf")
        assert path.name == "my_combined.dxf"

    def test_single_floor_building_combined(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        rooms = [_room(RoomType.LIVING_ROOM, 0, 0, 5, 5)]
        b = _building([_floor_plan(rooms)])
        path = DXFExporter().export_combined(b, tmp_path)
        assert path.exists()

    def test_output_dir_created_if_missing(self, tmp_path):
        from civilengineer.output_layer.dxf_exporter import DXFExporter
        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        b = _simple_building()
        DXFExporter().export_combined(b, new_dir)
        assert new_dir.exists()


# ---------------------------------------------------------------------------
# PDF Exporter Tests
# ---------------------------------------------------------------------------


class TestPDFExporter:
    def test_export_creates_pdf(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        b = _simple_building()
        path = PDFExporter().export(b, tmp_path)
        assert path.exists()
        assert path.suffix == ".pdf"

    def test_pdf_has_nonzero_size(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        b = _simple_building()
        path = PDFExporter().export(b, tmp_path)
        assert path.stat().st_size > 1000   # at least 1KB

    def test_pdf_with_compliance_report(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        b = _simple_building()
        report = {"compliant": True, "violations": [], "warnings": []}
        path = PDFExporter().export(b, tmp_path, compliance_report=report)
        assert path.exists()

    def test_pdf_with_cost_estimate(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        from civilengineer.output_layer.cost_estimator import CostEstimator
        b = _simple_building()
        est = CostEstimator("standard").estimate(b)
        path = PDFExporter().export(b, tmp_path, cost_estimate=est)
        assert path.exists()

    def test_custom_filename(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        b = _simple_building()
        path = PDFExporter().export(b, tmp_path, filename="report.pdf")
        assert path.name == "report.pdf"

    def test_output_dir_created_if_missing(self, tmp_path):
        from civilengineer.output_layer.pdf_exporter import PDFExporter
        new_dir = tmp_path / "docs"
        assert not new_dir.exists()
        b = _simple_building()
        PDFExporter().export(b, new_dir)
        assert new_dir.exists()


# ---------------------------------------------------------------------------
# Enhanced draw_node Tests
# ---------------------------------------------------------------------------


class TestDrawNodeEnhanced:
    """draw_node now produces PDF, combined DXF, site plan, cost estimate."""

    def _make_state(self, tmp_path) -> dict:
        """Build a minimal agent state that draw_node can process."""
        from civilengineer.schemas.design import BuildingDesign, FloorPlan, Rect2D
        b = _simple_building()
        fps = [fp.model_dump() for fp in b.floor_plans]
        return {
            "building_design": b.model_dump(),
            "floor_plans": fps,
            "session_id": "test-session",
            "output_dir": str(tmp_path),
            "project_id": "p1",
            "plot_info": {"area_sqm": 300.0, "width_m": 15, "depth_m": 20},
            "setbacks": [1.5, 1.5, 1.0, 1.0],
            "requirements": {"style": "modern"},
            "errors": [],
            "warnings": [],
        }

    def test_draw_node_returns_dxf_paths(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        assert "dxf_paths" in result
        assert len(result["dxf_paths"]) >= 2   # per-floor + combined + site + index

    def test_draw_node_returns_pdf_paths(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        assert "pdf_paths" in result
        assert len(result["pdf_paths"]) == 1
        assert result["pdf_paths"][0].endswith(".pdf")

    def test_pdf_file_exists(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        assert Path(result["pdf_paths"][0]).exists()

    def test_draw_node_returns_cost_estimate(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        assert "cost_estimate" in result
        assert result["cost_estimate"]["total_cost_inr"] > 0

    def test_draw_node_no_building_returns_error(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        state["building_design"] = None
        result = draw_node(state)
        assert result["errors"]

    def test_draw_node_no_floor_plans_returns_error(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        state["floor_plans"] = []
        result = draw_node(state)
        assert result["errors"]

    def test_draw_node_all_dxf_files_exist(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        for p in result.get("dxf_paths", []):
            assert Path(p).exists(), f"Missing DXF: {p}"

    def test_draw_node_summary_in_messages(self, tmp_path):
        from civilengineer.agent.nodes.draw_node import draw_node
        state = self._make_state(tmp_path)
        result = draw_node(state)
        assert result.get("messages")
        content = result["messages"][0].content
        assert "DXF" in content or "PDF" in content
