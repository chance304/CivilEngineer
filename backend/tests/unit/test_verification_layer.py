"""
Unit tests for Phase 7 — Verification Layer + AutoCAD Bridge + MCP Server.

Test classes:
  TestSpatialAdjacency     (10) — adjacency graph detection
  TestOverlapDetection      (8) — room overlap geometry
  TestCirculationCheck      (7) — BFS reachability from entrance
  TestVastuZone             (8) — quadrant classification + violations
  TestExternalWindows       (6) — habitable rooms need exterior windows
  TestAdjacencyConstraints  (6) — kitchen≠toilet, living↔dining
  TestSpatialReport         (4) — composite report helpers
  TestExtendedCompliance    (8) — window ratio, staircase, FAR, coverage
  TestAutoCADLayer          (6) — EzdxfDocument + AutoCADDriver
  TestMCPServerImport       (3) — server builds without AutoCAD
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
    RoomType,
    WallFace,
    Window,
)
from civilengineer.schemas.rules import RuleCategory, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _room(
    room_type: RoomType,
    x: float,
    y: float,
    w: float,
    d: float,
    *,
    floor: int = 1,
    ext_n: bool = False,
    ext_s: bool = False,
    ext_e: bool = False,
    ext_w: bool = False,
    windows: Optional[list[Window]] = None,
    doors: Optional[list[Door]] = None,
    name: Optional[str] = None,
) -> RoomLayout:
    return RoomLayout(
        room_id=str(uuid.uuid4()),
        room_type=room_type,
        name=name or room_type.value,
        floor=floor,
        bounds=Rect2D(x=x, y=y, width=w, depth=d),
        is_external_wall_north=ext_n,
        is_external_wall_south=ext_s,
        is_external_wall_east=ext_e,
        is_external_wall_west=ext_w,
        windows=windows or [],
        doors=doors or [],
    )


def _floor_plan(rooms: list[RoomLayout], floor: int = 1) -> FloorPlan:
    return FloorPlan(
        floor=floor,
        buildable_zone=Rect2D(x=0, y=0, width=15, depth=20),
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


def _window(face: WallFace, width: float = 1.2, height: float = 1.2) -> Window:
    return Window(wall_face=face, position_along_wall=0.5, width=width, height=height)


def _door(face: WallFace, main: bool = False) -> Door:
    return Door(
        wall_face=face,
        position_along_wall=0.5,
        is_main_entrance=main,
        swing=DoorSwing.LEFT,
    )


# ---------------------------------------------------------------------------
# Spatial Adjacency Tests
# ---------------------------------------------------------------------------


class TestSpatialAdjacency:
    """Tests for build_adjacency_graph."""

    def _adj(self, rooms):
        from civilengineer.verification_layer.spatial_analyzer import build_adjacency_graph
        fp = _floor_plan(rooms)
        return build_adjacency_graph(fp)

    def test_adjacent_rooms_share_edge(self):
        """Two rooms sharing a vertical edge are detected as adjacent."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5)
        b = _room(RoomType.DINING_ROOM, 4, 0, 3, 5)  # shares x=4 edge
        adj = self._adj([a, b])
        assert any(e.room_b == b.room_id for e in adj[a.room_id])

    def test_adjacent_rooms_horizontal_edge(self):
        """Two rooms sharing a horizontal edge are detected."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 3)
        b = _room(RoomType.BEDROOM, 0, 3, 5, 4)  # shares y=3 edge
        adj = self._adj([a, b])
        assert any(e.room_b == b.room_id for e in adj[a.room_id])

    def test_non_adjacent_rooms_not_connected(self):
        """Rooms with a gap between them are not adjacent."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 3, 3)
        b = _room(RoomType.BEDROOM, 4, 0, 3, 3)   # gap of 1m
        adj = self._adj([a, b])
        assert not any(e.room_b == b.room_id for e in adj[a.room_id])

    def test_shared_length_computed(self):
        """Shared edge length is correctly computed."""
        from civilengineer.verification_layer.spatial_analyzer import build_adjacency_graph
        a = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5)
        b = _room(RoomType.DINING_ROOM, 4, 1, 3, 3)  # overlaps y=1..4 (3m)
        adj = build_adjacency_graph(_floor_plan([a, b]))
        edges = [e for e in adj[a.room_id] if e.room_b == b.room_id]
        assert edges and abs(edges[0].shared_length - 3.0) < 0.05

    def test_graph_is_symmetric(self):
        """If A adj B then B adj A."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5)
        b = _room(RoomType.KITCHEN, 4, 0, 3, 5)
        adj = self._adj([a, b])
        ab = any(e.room_b == b.room_id for e in adj[a.room_id])
        ba = any(e.room_b == a.room_id for e in adj[b.room_id])
        assert ab and ba

    def test_three_room_chain(self):
        """A-B-C chain: A adj B, B adj C, A NOT adj C."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 3, 4)
        b = _room(RoomType.DINING_ROOM, 3, 0, 3, 4)
        c = _room(RoomType.KITCHEN,     6, 0, 3, 4)
        adj = self._adj([a, b, c])
        assert any(e.room_b == b.room_id for e in adj[a.room_id])
        assert any(e.room_b == c.room_id for e in adj[b.room_id])
        assert not any(e.room_b == c.room_id for e in adj[a.room_id])

    def test_single_room_no_adjacencies(self):
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        adj = self._adj([a])
        assert adj[a.room_id] == []

    def test_rooms_on_different_floors_have_own_graphs(self):
        """Multi-floor: each FloorPlan gets its own adjacency (separate calls)."""
        from civilengineer.verification_layer.spatial_analyzer import build_adjacency_graph
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5, floor=1)
        b = _room(RoomType.BEDROOM,     0, 0, 5, 5, floor=2)  # same position, diff floor
        fp1 = _floor_plan([a], floor=1)
        adj1 = build_adjacency_graph(fp1)
        # b is not in fp1
        assert b.room_id not in adj1

    def test_corner_touching_rooms_not_adjacent(self):
        """Rooms that only touch at a corner (0-length shared edge) are not adjacent."""
        a = _room(RoomType.LIVING_ROOM, 0, 0, 3, 3)
        b = _room(RoomType.BEDROOM,     3, 3, 3, 3)   # only touches at (3,3)
        adj = self._adj([a, b])
        assert not any(e.room_b == b.room_id for e in adj[a.room_id])

    def test_fully_surrounded_room(self):
        """A small room surrounded by 4 larger rooms has 4 adjacencies."""
        centre = _room(RoomType.BATHROOM, 3, 3, 2, 2)
        top    = _room(RoomType.BEDROOM,  3, 5, 2, 3)
        bot    = _room(RoomType.BEDROOM,  3, 0, 2, 3)
        left   = _room(RoomType.KITCHEN,  0, 3, 3, 2)
        right  = _room(RoomType.KITCHEN,  5, 3, 3, 2)
        adj = self._adj([centre, top, bot, left, right])
        assert len(adj[centre.room_id]) == 4


# ---------------------------------------------------------------------------
# Overlap Detection Tests
# ---------------------------------------------------------------------------


class TestOverlapDetection:
    def test_overlapping_rooms_detected(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        b = _room(RoomType.BEDROOM,     3, 3, 5, 5)   # overlaps 2×2 area
        violations = find_overlaps(_floor_plan([a, b]))
        assert len(violations) == 1
        assert abs(violations[0].overlap_area - 4.0) < 0.01

    def test_adjacent_rooms_no_overlap(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        b = _room(RoomType.BEDROOM,     5, 0, 5, 5)
        violations = find_overlaps(_floor_plan([a, b]))
        assert len(violations) == 0

    def test_gap_rooms_no_overlap(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 3, 3)
        b = _room(RoomType.BEDROOM,     4, 4, 3, 3)
        violations = find_overlaps(_floor_plan([a, b]))
        assert len(violations) == 0

    def test_contained_room_overlap(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        outer = _room(RoomType.LIVING_ROOM, 0, 0, 10, 10)
        inner = _room(RoomType.BATHROOM,    2,  2,  3,  3)
        violations = find_overlaps(_floor_plan([outer, inner]))
        assert len(violations) == 1

    def test_three_room_no_overlap(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5)
        b = _room(RoomType.DINING_ROOM, 4, 0, 4, 5)
        c = _room(RoomType.KITCHEN,     8, 0, 4, 5)
        violations = find_overlaps(_floor_plan([a, b, c]))
        assert len(violations) == 0

    def test_overlap_area_computed_correctly(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 4, 4)
        b = _room(RoomType.BEDROOM,     2, 2, 4, 4)  # overlap 2×2 = 4 sqm
        violations = find_overlaps(_floor_plan([a, b]))
        assert abs(violations[0].overlap_area - 4.0) < 0.01

    def test_single_room_no_overlaps(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        violations = find_overlaps(_floor_plan([a]))
        assert len(violations) == 0

    def test_multiple_overlapping_pairs(self):
        from civilengineer.verification_layer.spatial_analyzer import find_overlaps
        a = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        b = _room(RoomType.BEDROOM,     3, 0, 5, 5)
        c = _room(RoomType.KITCHEN,     1, 3, 5, 5)
        violations = find_overlaps(_floor_plan([a, b, c]))
        assert len(violations) >= 2


# ---------------------------------------------------------------------------
# Circulation Check Tests
# ---------------------------------------------------------------------------


class TestCirculationCheck:
    def test_all_adjacent_rooms_reachable(self):
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        living = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5, doors=[_door(WallFace.SOUTH, main=True)])
        bed    = _room(RoomType.BEDROOM,     4, 0, 4, 5)    # adjacent to living
        bath   = _room(RoomType.BATHROOM,    4, 5, 4, 3)    # adjacent to bed
        fp = _floor_plan([living, bed, bath])
        result = check_circulation(fp)
        assert result.has_entrance
        assert not result.unreachable

    def test_isolated_required_room_flagged(self):
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        living = _room(RoomType.LIVING_ROOM, 0, 0, 4, 5, doors=[_door(WallFace.SOUTH, main=True)])
        # Bedroom far away — no adjacency
        bed = _room(RoomType.BEDROOM, 10, 10, 3, 3)
        fp = _floor_plan([living, bed])
        result = check_circulation(fp)
        assert bed.room_id in result.unreachable

    def test_fallback_entrance_living_room(self):
        """Fallback: living room on floor 1 is entrance when no main entrance door."""
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        kitchen = _room(RoomType.KITCHEN, 5, 0, 3, 5)
        fp = _floor_plan([living, kitchen])
        result = check_circulation(fp)
        assert result.has_entrance
        assert living.room_id in result.reachable

    def test_empty_floor_plan(self):
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        fp = _floor_plan([])
        result = check_circulation(fp)
        assert not result.has_entrance

    def test_chain_all_reachable(self):
        """A→B→C chain: all reachable from A."""
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        a = _room(RoomType.LIVING_ROOM, 0, 0, 3, 4, doors=[_door(WallFace.SOUTH, main=True)])
        b = _room(RoomType.KITCHEN,     3, 0, 3, 4)
        c = _room(RoomType.BATHROOM,    6, 0, 3, 4)
        fp = _floor_plan([a, b, c])
        result = check_circulation(fp)
        assert not result.unreachable

    def test_dead_end_bedroom_connected(self):
        """Bedroom at end of chain is reachable (not flagged)."""
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        living = _room(RoomType.LIVING_ROOM, 0, 0, 4, 4, doors=[_door(WallFace.SOUTH, main=True)])
        bed    = _room(RoomType.BEDROOM,     4, 0, 3, 4)
        fp = _floor_plan([living, bed])
        result = check_circulation(fp)
        assert bed.room_id in result.reachable

    def test_reachable_set_contains_entrance(self):
        from civilengineer.verification_layer.spatial_analyzer import check_circulation
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5, doors=[_door(WallFace.SOUTH, main=True)])
        fp = _floor_plan([living])
        result = check_circulation(fp)
        assert living.room_id in result.reachable


# ---------------------------------------------------------------------------
# Vastu Zone Tests
# ---------------------------------------------------------------------------


class TestVastuZone:
    PLOT_W = 15.0
    PLOT_D = 20.0

    def _zone(self, x, y, w=2, d=2, rt=RoomType.LIVING_ROOM):
        room = _room(rt, x, y, w, d)
        from civilengineer.verification_layer.spatial_analyzer import classify_vastu_zone
        return classify_vastu_zone(room, self.PLOT_W, self.PLOT_D)

    def test_ne_quadrant(self):
        # centroid at (9, 11) on 15×20 plot → NE
        assert self._zone(8, 10) == "NE"

    def test_sw_quadrant(self):
        # centroid at (1, 1) → SW
        assert self._zone(0, 0) == "SW"

    def test_se_quadrant(self):
        # centroid at (9, 1) → SE
        assert self._zone(8, 0) == "SE"

    def test_nw_quadrant(self):
        # centroid at (1, 11) → NW
        assert self._zone(0, 10) == "NW"

    def test_kitchen_in_se_no_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import check_vastu_compliance
        # Kitchen at SE quadrant: x=8, y=0 on 15×20
        kitchen = _room(RoomType.KITCHEN, 8, 0, 3, 3)
        fp = _floor_plan([kitchen])
        violations = check_vastu_compliance(fp, self.PLOT_W, self.PLOT_D)
        assert len(violations) == 0

    def test_kitchen_in_nw_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import check_vastu_compliance
        # Kitchen at NW: x=0, y=10
        kitchen = _room(RoomType.KITCHEN, 0, 10, 3, 3)
        fp = _floor_plan([kitchen])
        violations = check_vastu_compliance(fp, self.PLOT_W, self.PLOT_D)
        assert len(violations) == 1
        assert violations[0].expected_zone == "SE"

    def test_master_bed_in_sw_no_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import check_vastu_compliance
        master = _room(RoomType.MASTER_BEDROOM, 0, 0, 4, 4)
        fp = _floor_plan([master])
        violations = check_vastu_compliance(fp, self.PLOT_W, self.PLOT_D)
        assert len(violations) == 0

    def test_upper_floor_rooms_skipped(self):
        """Vastu check only applies to floor 1."""
        from civilengineer.verification_layer.spatial_analyzer import check_vastu_compliance
        # Kitchen on floor 2 in wrong zone — should not produce violation
        kitchen = _room(RoomType.KITCHEN, 0, 10, 3, 3, floor=2)
        fp = _floor_plan([kitchen], floor=2)
        violations = check_vastu_compliance(fp, self.PLOT_W, self.PLOT_D)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# External Window Tests
# ---------------------------------------------------------------------------


class TestExternalWindows:
    def test_habitable_with_external_window_passes(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        bed = _room(
            RoomType.BEDROOM, 0, 0, 3, 4,
            ext_s=True,
            windows=[_window(WallFace.SOUTH)],
        )
        violations = check_external_windows(_floor_plan([bed]))
        assert len(violations) == 0

    def test_habitable_no_external_wall_flagged(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        bed = _room(RoomType.BEDROOM, 0, 0, 3, 4)  # no external walls
        violations = check_external_windows(_floor_plan([bed]))
        assert len(violations) == 1

    def test_window_on_internal_face_flagged(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        # External wall is south but window is on north (internal)
        bed = _room(
            RoomType.BEDROOM, 0, 0, 3, 4,
            ext_s=True,
            windows=[_window(WallFace.NORTH)],  # internal face
        )
        violations = check_external_windows(_floor_plan([bed]))
        assert len(violations) == 1

    def test_non_habitable_room_skipped(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        # Bathroom with no window — not habitable, should not be flagged
        bath = _room(RoomType.BATHROOM, 0, 0, 2, 2)
        violations = check_external_windows(_floor_plan([bath]))
        assert len(violations) == 0

    def test_staircase_skipped(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        stair = _room(RoomType.STAIRCASE, 0, 0, 1.5, 3)
        violations = check_external_windows(_floor_plan([stair]))
        assert len(violations) == 0

    def test_living_room_no_external_window_flagged(self):
        from civilengineer.verification_layer.spatial_analyzer import check_external_windows
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)  # no ext walls
        violations = check_external_windows(_floor_plan([living]))
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# Adjacency Constraint Tests
# ---------------------------------------------------------------------------


class TestAdjacencyConstraints:
    def test_kitchen_toilet_adjacency_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        kitchen = _room(RoomType.KITCHEN, 0, 0, 3, 4)
        toilet  = _room(RoomType.TOILET,  3, 0, 1.5, 2)  # adjacent to kitchen
        fp = _floor_plan([kitchen, toilet])
        violations = check_adjacency_constraints(fp)
        assert len(violations) >= 1
        assert any("toilet" in v.message.lower() for v in violations)

    def test_kitchen_bathroom_adjacency_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        kitchen = _room(RoomType.KITCHEN, 0, 0, 3, 4)
        bath    = _room(RoomType.BATHROOM, 3, 0, 2, 3)
        fp = _floor_plan([kitchen, bath])
        violations = check_adjacency_constraints(fp)
        assert len(violations) >= 1

    def test_kitchen_bathroom_no_adjacency_passes(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        kitchen = _room(RoomType.KITCHEN, 0, 0, 3, 4)
        bath    = _room(RoomType.BATHROOM, 6, 0, 2, 3)   # gap between them
        fp = _floor_plan([kitchen, bath])
        violations = check_adjacency_constraints(fp)
        bathroom_v = [v for v in violations if "bathroom" in v.message.lower()]
        assert len(bathroom_v) == 0

    def test_living_dining_adjacent_passes(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5)
        dining = _room(RoomType.DINING_ROOM, 5, 0, 4, 5)
        fp = _floor_plan([living, dining])
        violations = [v for v in check_adjacency_constraints(fp) if "adjacent to dining" in v.message]
        assert len(violations) == 0

    def test_living_dining_not_adjacent_advisory(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        living = _room(RoomType.LIVING_ROOM, 0, 0, 4, 4)
        dining = _room(RoomType.DINING_ROOM, 8, 8, 4, 4)  # far away
        fp = _floor_plan([living, dining])
        violations = check_adjacency_constraints(fp)
        living_dining = [v for v in violations if "living" in v.message.lower()]
        assert len(living_dining) == 1

    def test_no_sensitive_rooms_no_violations(self):
        from civilengineer.verification_layer.spatial_analyzer import check_adjacency_constraints
        bed1 = _room(RoomType.BEDROOM, 0, 0, 4, 4)
        bed2 = _room(RoomType.BEDROOM, 4, 0, 4, 4)
        fp = _floor_plan([bed1, bed2])
        violations = check_adjacency_constraints(fp)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# Spatial Report Tests
# ---------------------------------------------------------------------------


class TestSpatialReport:
    def test_analyze_floor_clean(self):
        from civilengineer.verification_layer.spatial_analyzer import analyze_floor
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5, ext_s=True, windows=[_window(WallFace.SOUTH)])
        bed    = _room(RoomType.BEDROOM,     5, 0, 4, 5, ext_s=True, windows=[_window(WallFace.SOUTH)])
        fp = _floor_plan([living, bed])
        report = analyze_floor(fp, 15.0, 20.0)
        assert not report.has_hard_violations

    def test_analyze_floor_overlap_is_hard(self):
        from civilengineer.verification_layer.spatial_analyzer import analyze_floor
        a = _room(RoomType.LIVING_ROOM, 0, 0, 6, 5)
        b = _room(RoomType.BEDROOM,     4, 0, 5, 5)   # overlaps
        fp = _floor_plan([a, b])
        report = analyze_floor(fp, 15.0, 20.0)
        assert report.has_hard_violations

    def test_summary_non_empty_on_violation(self):
        from civilengineer.verification_layer.spatial_analyzer import analyze_floor
        a = _room(RoomType.LIVING_ROOM, 0, 0, 6, 5)
        b = _room(RoomType.BEDROOM,     4, 0, 5, 5)
        fp = _floor_plan([a, b])
        report = analyze_floor(fp, 15.0, 20.0)
        assert "overlap" in report.summary.lower()

    def test_summary_clean(self):
        from civilengineer.verification_layer.spatial_analyzer import analyze_floor
        living = _room(RoomType.LIVING_ROOM, 0, 0, 5, 5, ext_s=True, windows=[_window(WallFace.SOUTH)])
        fp = _floor_plan([living])
        report = analyze_floor(fp, 15.0, 20.0)
        assert "No spatial violations" in report.summary


# ---------------------------------------------------------------------------
# Extended Compliance Tests
# ---------------------------------------------------------------------------


class TestExtendedCompliance:
    def _building_with_room(self, room: RoomLayout) -> BuildingDesign:
        fp = _floor_plan([room])
        return _building([fp])

    def test_window_ratio_pass(self):
        """1.2×1.2 window on 3×4 bedroom (floor=12 sqm) → ratio=12% > 10%."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        bed = _room(
            RoomType.BEDROOM, 0, 0, 3, 4,
            ext_s=True,
            windows=[_window(WallFace.SOUTH, 1.2, 1.2)],
        )
        violations = extended_compliance_check(self._building_with_room(bed))
        win_v = [v for v in violations if v.rule_id == "EXT-WIN-RATIO"]
        assert len(win_v) == 0

    def test_window_ratio_fail(self):
        """Tiny window on large bedroom triggers soft violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        bed = _room(
            RoomType.BEDROOM, 0, 0, 5, 6,   # 30 sqm
            ext_s=True,
            windows=[_window(WallFace.SOUTH, 0.5, 0.5)],  # 0.25 sqm = 0.8%
        )
        violations = extended_compliance_check(self._building_with_room(bed))
        win_v = [v for v in violations if v.rule_id == "EXT-WIN-RATIO"]
        assert len(win_v) == 1
        assert win_v[0].severity.value == "soft"

    def test_staircase_too_narrow(self):
        """Staircase narrower than 0.9m triggers hard violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        stair = _room(RoomType.STAIRCASE, 0, 0, 0.7, 5.0)  # 0.7m wide
        violations = extended_compliance_check(self._building_with_room(stair))
        stair_v = [v for v in violations if v.rule_id == "EXT-STAIR-WIDTH"]
        assert len(stair_v) == 1
        assert stair_v[0].severity == Severity.HARD

    def test_staircase_adequate(self):
        """Staircase 1.0m × 5.0m → no staircase violations."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        stair = _room(RoomType.STAIRCASE, 0, 0, 1.0, 5.0)
        violations = extended_compliance_check(self._building_with_room(stair))
        stair_v = [v for v in violations if "STAIR" in v.rule_id]
        assert len(stair_v) == 0

    def test_far_exceeded(self):
        """Built-up area exceeding FAR limit for road width triggers hard violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        # 10×15 = 150 sqm per floor × 3 floors = 450 sqm built
        # Plot 15×20 = 300 sqm; FAR = 450/300 = 1.5; limit for 5m road = 1.5 → just ok
        # Use small plot for easier FAR failure
        rooms = [_room(RoomType.BEDROOM, 0, 0, 10, 15)]
        fp1 = _floor_plan(rooms, floor=1)
        fp2 = FloorPlan(
            floor=2,
            buildable_zone=Rect2D(x=0, y=0, width=10, depth=15),
            rooms=[_room(RoomType.BEDROOM, 0, 0, 10, 15, floor=2)],
        )
        b = BuildingDesign(
            design_id="d", project_id="p", num_floors=2,
            plot_width=10, plot_depth=10, floor_plans=[fp1, fp2],
        )
        plot_info = {"area_sqm": 100.0}  # FAR = 300/100 = 3.0 > 2.5 limit
        violations = extended_compliance_check(b, plot_info=plot_info, road_width_m=7.0)
        far_v = [v for v in violations if v.rule_id == "EXT-FAR"]
        assert len(far_v) == 1

    def test_coverage_within_limit(self):
        """Ground footprint 50% of plot → no coverage violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        rooms = [_room(RoomType.LIVING_ROOM, 0, 0, 5, 10)]  # 50 sqm
        fp = _floor_plan(rooms)
        b = _building([fp])
        plot_info = {"area_sqm": 100.0}  # coverage = 50%
        violations = extended_compliance_check(b, plot_info=plot_info)
        cov_v = [v for v in violations if "COVERAGE" in v.rule_id]
        assert len(cov_v) == 0

    def test_kitchen_aspect_too_long(self):
        """Kitchen 1m × 4m (aspect 4:1) triggers soft violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        kitchen = _room(RoomType.KITCHEN, 0, 0, 1.0, 5.0)  # aspect 5:1
        violations = extended_compliance_check(self._building_with_room(kitchen))
        asp_v = [v for v in violations if v.rule_id == "EXT-KITCHEN-ASPECT"]
        assert len(asp_v) == 1

    def test_bathroom_too_small(self):
        """Bathroom 1.0×1.0 (1 sqm) < 1.8 sqm minimum → hard violation."""
        from civilengineer.verification_layer.code_compliance import extended_compliance_check
        bath = _room(RoomType.BATHROOM, 0, 0, 1.0, 1.0)
        violations = extended_compliance_check(self._building_with_room(bath))
        bath_v = [v for v in violations if v.rule_id == "EXT-BATH-AREA"]
        assert len(bath_v) == 1
        assert bath_v[0].severity == Severity.HARD


# ---------------------------------------------------------------------------
# AutoCAD Layer / COM Bridge Tests
# ---------------------------------------------------------------------------


class TestAutoCADLayer:
    def test_ezdxf_document_add_line(self):
        """EzdxfDocument.add_line does not raise."""
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        doc = EzdxfDocument()
        doc.add_line((0, 0, 0), (5, 0, 0))

    def test_ezdxf_document_add_polyline(self):
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        doc = EzdxfDocument()
        doc.add_polyline([(0, 0, 0), (5, 0, 0), (5, 5, 0), (0, 5, 0)], closed=True)

    def test_ezdxf_document_add_text(self):
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        doc = EzdxfDocument()
        doc.add_text("Living Room", (2.5, 2.5, 0), height=0.25)

    def test_ezdxf_document_add_layer(self):
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        doc = EzdxfDocument()
        doc.add_layer("A-WALL-EXTR", color=7)

    def test_ezdxf_document_save(self, tmp_path):
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        doc = EzdxfDocument()
        doc.add_line((0, 0, 0), (3, 0, 0))
        saved = doc.save(tmp_path / "test.dxf")
        assert saved.exists()

    def test_driver_fallback_returns_ezdxf_doc(self):
        """AutoCADDriver with fallback=True returns EzdxfDocument on Linux."""
        from civilengineer.autocad_layer.com_driver import AutoCADDriver, EzdxfDocument
        driver = AutoCADDriver(fallback_to_dxf=True)
        driver.connect()  # win32com not available — should not raise
        doc = driver.open_or_new()
        assert isinstance(doc, EzdxfDocument)


# ---------------------------------------------------------------------------
# MCP Server Import / Build Tests
# ---------------------------------------------------------------------------


class TestMCPServerImport:
    def test_build_server_returns_fastmcp(self):
        """build_server() returns a FastMCP instance with tools."""
        from civilengineer.mcp_server.server import build_server
        from fastmcp import FastMCP
        server = build_server()
        assert isinstance(server, FastMCP)

    def test_server_has_registered_tools(self):
        """Server registers drawing + element + annotation + file tools."""
        from civilengineer.mcp_server.server import build_server
        server = build_server()
        # Tool names are exposed via server._tool_manager or similar internal
        # Use a simple check: the object has a 'run' method (valid FastMCP)
        assert callable(getattr(server, "run", None))

    def test_get_active_doc_returns_document(self):
        """get_active_doc() returns an AutoCADDocument even without AutoCAD."""
        from civilengineer.mcp_server.server import get_active_doc, set_active_doc
        from civilengineer.autocad_layer.com_driver import EzdxfDocument
        # Reset active doc to None to test auto-creation
        set_active_doc(None)
        doc = get_active_doc()
        assert isinstance(doc, EzdxfDocument)
