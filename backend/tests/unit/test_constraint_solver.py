"""
Unit tests for Phase 5 — Constraint Solver + Geometry Engine.

Test classes
------------
TestValidator           — input_layer.validator
TestEnricher            — input_layer.enricher
TestRoomSizing          — constraint_solver room-sizing phase
TestSolverSAT           — full solve on feasible problems
TestSolverUNSAT         — infeasible problems correctly reported
TestMultiFloor          — two-floor solve + staircase alignment
TestFloorAssignment     — _assign_floors heuristic
TestLayoutGenerator     — geometry_engine.layout_generator
TestWallBuilder         — geometry_engine.wall_builder
"""

from __future__ import annotations

import pytest

from civilengineer.geometry_engine.layout_generator import generate_floor_plans
from civilengineer.geometry_engine.wall_builder import build_walls
from civilengineer.input_layer.enricher import Enricher
from civilengineer.input_layer.validator import validate_requirements
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.reasoning_engine.constraint_solver import (
    SolveStatus,
    _assign_floors,
    _size_rooms,
    solve_layout,
)
from civilengineer.schemas.design import (
    DesignRequirements,
    Rect2D,
    RoomRequirement,
    RoomType,
)
from civilengineer.schemas.project import PlotInfo, PlotFacing

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

RULES = load_rules()


def _plot(width_m: float = 15.0, depth_m: float = 20.0) -> PlotInfo:
    return PlotInfo(
        dwg_storage_key="test.dxf",
        polygon=[],
        area_sqm=width_m * depth_m,
        width_m=width_m,
        depth_m=depth_m,
        is_rectangular=True,
        north_direction_deg=0.0,
        facing=PlotFacing.SOUTH,
        scale_factor=1.0,
        extraction_confidence=0.95,
    )


def _req_1bhk(num_floors: int = 1, road_width: float = 7.0) -> DesignRequirements:
    return DesignRequirements(
        project_id="test",
        num_floors=num_floors,
        road_width_m=road_width,
        rooms=[
            RoomRequirement(room_type=RoomType.LIVING_ROOM),
            RoomRequirement(room_type=RoomType.KITCHEN),
            RoomRequirement(room_type=RoomType.BEDROOM),
            RoomRequirement(room_type=RoomType.BATHROOM),
        ],
    )


def _req_3bhk(num_floors: int = 2, road_width: float = 7.0) -> DesignRequirements:
    return DesignRequirements(
        project_id="test",
        num_floors=num_floors,
        road_width_m=road_width,
        rooms=[
            RoomRequirement(room_type=RoomType.LIVING_ROOM),
            RoomRequirement(room_type=RoomType.DINING_ROOM),
            RoomRequirement(room_type=RoomType.KITCHEN),
            RoomRequirement(room_type=RoomType.MASTER_BEDROOM),
            RoomRequirement(room_type=RoomType.BEDROOM),
            RoomRequirement(room_type=RoomType.BEDROOM),
            RoomRequirement(room_type=RoomType.BATHROOM),
            RoomRequirement(room_type=RoomType.BATHROOM),
            RoomRequirement(room_type=RoomType.TOILET),
            RoomRequirement(room_type=RoomType.STAIRCASE),
        ],
    )


def _zone(width: float = 10.0, depth: float = 15.0) -> Rect2D:
    return Rect2D(x=3.0, y=4.5, width=width, depth=depth)


# ===========================================================================
# TestValidator
# ===========================================================================

class TestValidator:

    def test_valid_3bhk_passes(self):
        result = validate_requirements(_req_3bhk(), _plot())
        assert result.is_valid, result.errors

    def test_empty_rooms_is_error(self):
        req = DesignRequirements(project_id="t", num_floors=1, rooms=[])
        result = validate_requirements(req, _plot())
        assert not result.is_valid
        assert any("No rooms" in e for e in result.errors)

    def test_no_habitable_room_is_error(self):
        req = DesignRequirements(
            project_id="t",
            num_floors=1,
            rooms=[RoomRequirement(room_type=RoomType.TOILET)],
        )
        result = validate_requirements(req, _plot())
        assert not result.is_valid
        assert any("habitable" in e for e in result.errors)

    def test_no_kitchen_is_warning_not_error(self):
        req = DesignRequirements(
            project_id="t",
            num_floors=1,
            rooms=[
                RoomRequirement(room_type=RoomType.LIVING_ROOM),
                RoomRequirement(room_type=RoomType.BEDROOM),
                RoomRequirement(room_type=RoomType.BATHROOM),
            ],
        )
        result = validate_requirements(req, _plot())
        assert result.is_valid
        assert any("kitchen" in w.lower() for w in result.warnings)

    def test_too_many_rooms_for_tiny_plot_is_error(self):
        tiny_plot = _plot(width_m=5.0, depth_m=5.0)  # 25 sqm
        result = validate_requirements(_req_3bhk(), tiny_plot)
        assert not result.is_valid
        assert any("FAR" in e or "sqm" in e for e in result.errors)

    def test_multi_floor_without_staircase_warns(self):
        req = _req_1bhk(num_floors=2)
        result = validate_requirements(req, _plot())
        assert any("staircase" in w.lower() for w in result.warnings)

    def test_zero_floors_is_error(self):
        req = DesignRequirements(project_id="t", num_floors=0, rooms=[
            RoomRequirement(room_type=RoomType.BEDROOM),
        ])
        result = validate_requirements(req, _plot())
        assert not result.is_valid

    def test_bedrooms_without_bathroom_warns(self):
        req = DesignRequirements(
            project_id="t",
            num_floors=1,
            rooms=[
                RoomRequirement(room_type=RoomType.BEDROOM),
                RoomRequirement(room_type=RoomType.KITCHEN),
            ],
        )
        result = validate_requirements(req, _plot())
        assert result.is_valid
        assert any("bathroom" in w.lower() for w in result.warnings)


# ===========================================================================
# TestEnricher
# ===========================================================================

class TestEnricher:

    def setup_method(self):
        self.enricher = Enricher(RULES.rules)

    def test_front_setback_narrow_road(self):
        # NP_KTM_SETB_101: road < 6m → 1.5m
        front, rear, left, right = self.enricher.setbacks(_plot(), road_width_m=4.0)
        assert front == pytest.approx(1.5)

    def test_front_setback_medium_road(self):
        # NP_KTM_SETB_102: road 6–8m → 1.5m
        front, rear, left, right = self.enricher.setbacks(_plot(), road_width_m=7.0)
        assert front == pytest.approx(1.5)

    def test_front_setback_wide_road(self):
        # NP_KTM_SETB_103: road 8–11m → 2.0m
        front, rear, left, right = self.enricher.setbacks(_plot(), road_width_m=9.0)
        assert front == pytest.approx(2.0)

    def test_buildable_zone_dimensions(self):
        zone = self.enricher.buildable_zone(_plot(15.0, 20.0), road_width_m=7.0)
        # Actual rules: front=1.5 (road 7m → SETB_102), rear=1.5, side=1.0 (≤3 floors)
        assert zone.width  == pytest.approx(15.0 - 1.0 - 1.0)   # 13.0
        assert zone.depth  == pytest.approx(20.0 - 1.5 - 1.5)   # 17.0
        assert zone.x      == pytest.approx(1.0)
        assert zone.y      == pytest.approx(1.5)

    def test_buildable_zone_positive(self):
        zone = self.enricher.buildable_zone(_plot(15.0, 20.0), road_width_m=5.0)
        assert zone.width > 0
        assert zone.depth > 0

    def test_no_road_width_uses_fallback(self):
        front, *_ = self.enricher.setbacks(_plot(), road_width_m=None)
        assert front > 0


# ===========================================================================
# TestRoomSizing
# ===========================================================================

class TestRoomSizing:

    def test_bedroom_meets_min_area(self):
        req = _req_3bhk()
        rooms_with_floors = _assign_floors(req, [])
        sized = _size_rooms(rooms_with_floors, RULES.rules, _zone(), [])
        bedrooms = [s for s in sized if s.room_req.room_type == RoomType.BEDROOM]
        for b in bedrooms:
            assert b.area >= 9.5, f"Bedroom area {b.area:.2f} < 9.5 sqm"

    def test_master_bedroom_meets_min_area(self):
        req = _req_3bhk()
        rooms_with_floors = _assign_floors(req, [])
        sized = _size_rooms(rooms_with_floors, RULES.rules, _zone(), [])
        masters = [s for s in sized if s.room_req.room_type == RoomType.MASTER_BEDROOM]
        for m in masters:
            assert m.area >= 12.0, f"Master bedroom area {m.area:.2f} < 12.0 sqm"

    def test_kitchen_meets_min_dimension(self):
        req = _req_3bhk()
        rooms_with_floors = _assign_floors(req, [])
        sized = _size_rooms(rooms_with_floors, RULES.rules, _zone(), [])
        kitchens = [s for s in sized if s.room_req.room_type == RoomType.KITCHEN]
        for k in kitchens:
            assert min(k.width, k.depth) >= 2.4, \
                f"Kitchen min dim {min(k.width, k.depth):.2f} < 2.4 m"

    def test_custom_min_area_respected(self):
        req = DesignRequirements(
            project_id="t", num_floors=1,
            rooms=[RoomRequirement(room_type=RoomType.BEDROOM, min_area=15.0)],
        )
        rooms_with_floors = _assign_floors(req, [])
        sized = _size_rooms(rooms_with_floors, RULES.rules, _zone(), [])
        bedrooms = [s for s in sized if s.room_req.room_type == RoomType.BEDROOM]
        assert len(bedrooms) == 1
        assert bedrooms[0].area >= 15.0


# ===========================================================================
# TestFloorAssignment
# ===========================================================================

class TestFloorAssignment:

    def test_living_room_goes_to_floor_1(self):
        req = _req_3bhk(num_floors=2)
        assignments = _assign_floors(req, [])
        living = [f for r, f in assignments if r.room_type == RoomType.LIVING_ROOM]
        assert all(f == 1 for f in living)

    def test_bedrooms_go_to_upper_floors_if_multi_floor(self):
        req = _req_3bhk(num_floors=2)
        assignments = _assign_floors(req, [])
        beds = [f for r, f in assignments
                if r.room_type in (RoomType.BEDROOM, RoomType.MASTER_BEDROOM)]
        assert all(f >= 2 for f in beds)

    def test_staircase_on_every_floor(self):
        req = _req_3bhk(num_floors=3)
        assignments = _assign_floors(req, [])
        stair_floors = sorted(set(f for r, f in assignments
                                  if r.room_type == RoomType.STAIRCASE))
        assert stair_floors == [1, 2, 3]

    def test_single_floor_all_rooms_on_floor_1(self):
        req = _req_1bhk(num_floors=1)
        assignments = _assign_floors(req, [])
        # Staircase auto-injected on floor 1 in solver; other rooms all floor 1
        non_stair = [f for r, f in assignments if r.room_type != RoomType.STAIRCASE]
        assert all(f == 1 for f in non_stair)

    def test_explicit_floor_respected(self):
        req = DesignRequirements(
            project_id="t",
            num_floors=2,
            rooms=[RoomRequirement(room_type=RoomType.BEDROOM, floor=1)],
        )
        assignments = _assign_floors(req, [])
        bed_floors = [f for r, f in assignments if r.room_type == RoomType.BEDROOM]
        assert bed_floors == [1]


# ===========================================================================
# TestSolverSAT
# ===========================================================================

class TestSolverSAT:

    def test_1bhk_single_floor_sat(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.status == SolveStatus.SAT, \
            f"Expected SAT, got {result.status}. Unplaced: {result.unplaced_rooms}. Warnings: {result.warnings}"

    def test_all_rooms_placed(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        # +1 staircase auto-added for multi-floor; 1 floor so no staircase
        assert len(result.unplaced_rooms) == 0

    def test_no_overlapping_rooms(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.status in (SolveStatus.SAT, SolveStatus.PARTIAL)

        placed_per_floor: dict[int, list] = {}
        for pr in result.placed_rooms:
            placed_per_floor.setdefault(pr.floor, []).append(pr)

        for floor_num, rooms in placed_per_floor.items():
            for i, a in enumerate(rooms):
                for b in rooms[i + 1:]:
                    overlap = _rect_overlap(
                        a.x, a.y, a.width, a.depth,
                        b.x, b.y, b.width, b.depth,
                    )
                    assert not overlap, (
                        f"Floor {floor_num}: rooms overlap: "
                        f"{a.room_req.room_type} @ ({a.x},{a.y}) vs "
                        f"{b.room_req.room_type} @ ({b.x},{b.y})"
                    )

    def test_all_rooms_within_buildable_zone(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        for pr in result.placed_rooms:
            assert pr.x >= -0.01
            assert pr.y >= -0.01
            assert pr.x + pr.width  <= zone.width  + 0.01, \
                f"Room {pr.room_req.room_type} extends beyond zone width"
            assert pr.y + pr.depth  <= zone.depth  + 0.01, \
                f"Room {pr.room_req.room_type} extends beyond zone depth"

    def test_solver_time_reported(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.solver_time_s >= 0.0

    def test_buildable_zone_in_result(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.buildable_zone.width == pytest.approx(zone.width)
        assert result.buildable_zone.depth == pytest.approx(zone.depth)


# ===========================================================================
# TestSolverUNSAT
# ===========================================================================

class TestSolverUNSAT:

    def test_impossible_rooms_on_tiny_zone(self):
        """10 rooms cannot fit in a 3×3 m zone."""
        req = _req_3bhk(num_floors=1)
        tiny_zone = Rect2D(x=0.0, y=0.0, width=3.0, depth=3.0)
        result = solve_layout(req, tiny_zone, RULES.rules, timeout_s=10.0)
        assert result.status in (SolveStatus.UNSAT, SolveStatus.PARTIAL)
        assert len(result.placed_rooms) == 0 or len(result.unplaced_rooms) > 0

    def test_unsat_has_warnings(self):
        req = _req_3bhk(num_floors=1)
        tiny_zone = Rect2D(x=0.0, y=0.0, width=2.0, depth=2.0)
        result = solve_layout(req, tiny_zone, RULES.rules, timeout_s=5.0)
        # Either unplaced rooms or warnings about rooms not fitting
        assert len(result.unplaced_rooms) > 0 or len(result.warnings) > 0


# ===========================================================================
# TestMultiFloor
# ===========================================================================

class TestMultiFloor:

    def test_3bhk_two_floors_sat(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.status in (SolveStatus.SAT, SolveStatus.PARTIAL)
        assert len(result.floors_solved) >= 1

    def test_floors_1_and_2_both_solved(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert 1 in result.floors_solved
        assert 2 in result.floors_solved

    def test_staircase_same_position_both_floors(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        stairs = [pr for pr in result.placed_rooms if pr.room_req.room_type == RoomType.STAIRCASE]
        assert len(stairs) == 2, f"Expected 2 staircases (1 per floor), got {len(stairs)}"
        s1 = next(s for s in stairs if s.floor == 1)
        s2 = next(s for s in stairs if s.floor == 2)
        assert s1.x == pytest.approx(s2.x, abs=0.15)
        assert s1.y == pytest.approx(s2.y, abs=0.15)

    def test_ground_floor_has_living_room(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        living_floor1 = [
            pr for pr in result.placed_rooms
            if pr.room_req.room_type == RoomType.LIVING_ROOM and pr.floor == 1
        ]
        assert len(living_floor1) == 1

    def test_upper_floor_has_bedrooms(self):
        req = _req_3bhk(num_floors=2)
        zone = _zone(width=11.0, depth=14.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        beds_upper = [
            pr for pr in result.placed_rooms
            if pr.room_req.room_type in (RoomType.BEDROOM, RoomType.MASTER_BEDROOM)
            and pr.floor >= 2
        ]
        assert len(beds_upper) >= 2


# ===========================================================================
# TestLayoutGenerator
# ===========================================================================

class TestLayoutGenerator:

    def _make_floor_plans(self, num_floors: int = 1):
        req = _req_1bhk(num_floors=num_floors)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        assert result.status == SolveStatus.SAT
        enricher = Enricher(RULES.rules)
        plot = _plot(15.0, 20.0)
        setbacks = enricher.setbacks(plot, road_width_m=7.0)
        return generate_floor_plans(result, req, plot, setbacks)

    def test_returns_floor_plan_list(self):
        fps = self._make_floor_plans()
        assert isinstance(fps, list)
        assert len(fps) >= 1

    def test_floor_plan_has_correct_floor_number(self):
        fps = self._make_floor_plans()
        assert fps[0].floor == 1

    def test_rooms_have_ids(self):
        fps = self._make_floor_plans()
        for fp in fps:
            for room in fp.rooms:
                assert room.room_id, "Room has no ID"

    def test_rooms_have_bounds_in_plot_coordinates(self):
        fps = self._make_floor_plans()
        zone = fps[0].buildable_zone
        for fp in fps:
            for room in fp.rooms:
                # bounds must be at or beyond zone origin
                assert room.bounds.x >= zone.x - 0.01
                assert room.bounds.y >= zone.y - 0.01

    def test_external_wall_flags_set_for_boundary_rooms(self):
        fps = self._make_floor_plans()
        # At least one room should have an external wall flag set
        has_external = any(
            room.is_external_wall_north
            or room.is_external_wall_south
            or room.is_external_wall_east
            or room.is_external_wall_west
            for fp in fps
            for room in fp.rooms
        )
        assert has_external

    def test_habitable_rooms_have_windows(self):
        fps = self._make_floor_plans()
        habitable_with_external = [
            room for fp in fps for room in fp.rooms
            if room.room_type in {RoomType.LIVING_ROOM, RoomType.BEDROOM}
            and (room.is_external_wall_north or room.is_external_wall_south
                 or room.is_external_wall_east or room.is_external_wall_west)
        ]
        for room in habitable_with_external:
            assert len(room.windows) >= 1, \
                f"{room.room_type} on external wall has no window"

    def test_all_rooms_have_at_least_one_door(self):
        fps = self._make_floor_plans()
        for fp in fps:
            for room in fp.rooms:
                assert len(room.doors) >= 1, \
                    f"Room {room.room_id} ({room.room_type}) has no door"


# ===========================================================================
# TestWallBuilder
# ===========================================================================

class TestWallBuilder:

    def _make_floor_plan_with_walls(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        enricher = Enricher(RULES.rules)
        plot = _plot(15.0, 20.0)
        setbacks = enricher.setbacks(plot, road_width_m=7.0)
        fps = generate_floor_plans(result, req, plot, setbacks)
        for fp in fps:
            build_walls(fp)
        return fps

    def test_wall_segments_generated(self):
        fps = self._make_floor_plan_with_walls()
        for fp in fps:
            assert len(fp.wall_segments) > 0, "No wall segments generated"

    def test_external_walls_have_correct_flag(self):
        fps = self._make_floor_plan_with_walls()
        for fp in fps:
            for seg in fp.wall_segments:
                if seg.is_external:
                    assert seg.is_load_bearing

    def test_external_walls_thicker(self):
        fps = self._make_floor_plan_with_walls()
        for fp in fps:
            ext_walls = [s for s in fp.wall_segments if s.is_external]
            int_walls = [s for s in fp.wall_segments if not s.is_external]
            if ext_walls and int_walls:
                avg_ext = sum(s.thickness for s in ext_walls) / len(ext_walls)
                avg_int = sum(s.thickness for s in int_walls) / len(int_walls)
                assert avg_ext >= avg_int, "External walls should be at least as thick as internal"

    def test_no_duplicate_wall_segments(self):
        fps = self._make_floor_plan_with_walls()
        for fp in fps:
            keys = [
                (round(s.start.x, 2), round(s.start.y, 2),
                 round(s.end.x, 2), round(s.end.y, 2))
                for s in fp.wall_segments
            ]
            assert len(keys) == len(set(keys)), "Duplicate wall segments found"

    def test_wall_builder_mutates_floor_plan(self):
        req = _req_1bhk(num_floors=1)
        zone = _zone(width=12.0, depth=12.0)
        result = solve_layout(req, zone, RULES.rules, timeout_s=30.0)
        enricher = Enricher(RULES.rules)
        plot = _plot(15.0, 20.0)
        setbacks = enricher.setbacks(plot, road_width_m=7.0)
        fps = generate_floor_plans(result, req, plot, setbacks)
        fp = fps[0]
        assert len(fp.wall_segments) == 0  # before
        build_walls(fp)
        assert len(fp.wall_segments) > 0   # after


# ===========================================================================
# Helpers
# ===========================================================================

def _rect_overlap(x1, y1, w1, d1, x2, y2, w2, d2, tol=0.01) -> bool:
    """Return True if two axis-aligned rectangles overlap (beyond tolerance)."""
    return not (
        x1 + w1 <= x2 + tol
        or x2 + w2 <= x1 + tol
        or y1 + d1 <= y2 + tol
        or y2 + d2 <= y1 + tol
    )
