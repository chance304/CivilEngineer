"""
Unit tests for Phase 4 — building-code rule engine.

Tests cover:
  - Rule compiler (loading rules.json → RuleSet)
  - Keyword retriever (no ChromaDB needed)
  - Rule engine: area, dimension, coverage, FAR, setback, floor height,
    window area, staircase width, vastu placement
  - Compliant design baseline (no violations)
"""

from __future__ import annotations

from civilengineer.knowledge.retriever import RuleRetriever
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.reasoning_engine.rule_engine import check_compliance
from civilengineer.schemas.design import (
    BuildingDesign,
    FloorPlan,
    Rect2D,
    RoomLayout,
    RoomType,
    Window,
    WallFace,
)
from civilengineer.schemas.rules import RuleCategory, Severity


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _rule_set():
    return load_rules()


def _room(
    room_type: RoomType,
    width: float,
    depth: float,
    floor: int = 1,
    windows: list[Window] | None = None,
) -> RoomLayout:
    """Build a minimal RoomLayout."""
    return RoomLayout(
        room_id=f"{room_type.value}_{width}x{depth}",
        room_type=room_type,
        name=room_type.value.replace("_", " ").title(),
        floor=floor,
        bounds=Rect2D(x=0.0, y=0.0, width=width, depth=depth),
        windows=windows or [],
    )


def _building(
    rooms: list[RoomLayout],
    plot_width: float = 15.0,
    plot_depth: float = 12.0,
    setback_front: float = 1.5,
    setback_rear: float = 1.5,
    setback_left: float = 1.0,
    setback_right: float = 1.0,
    num_floors: int = 2,
    floor_height: float = 2.8,
) -> BuildingDesign:
    buildable = Rect2D(
        x=setback_left,
        y=setback_rear,
        width=plot_width - setback_left - setback_right,
        depth=plot_depth - setback_front - setback_rear,
    )
    floor_plan = FloorPlan(
        floor=1,
        floor_height=floor_height,
        buildable_zone=buildable,
        rooms=rooms,
    )
    return BuildingDesign(
        design_id="test_design",
        project_id="test_project",
        jurisdiction="NP-KTM",
        num_floors=num_floors,
        plot_width=plot_width,
        plot_depth=plot_depth,
        setback_front=setback_front,
        setback_rear=setback_rear,
        setback_left=setback_left,
        setback_right=setback_right,
        floor_plans=[floor_plan],
    )


# ---------------------------------------------------------------------------
# 1. Rule compiler
# ---------------------------------------------------------------------------

class TestRuleCompiler:
    def test_loads_without_error(self):
        rs = _rule_set()
        assert len(rs.rules) > 0

    def test_jurisdiction(self):
        assert _rule_set().jurisdiction == "NP-KTM"

    def test_code_version(self):
        assert "NBC" in _rule_set().code_version

    def test_minimum_rule_count(self):
        # We authored 60+ rules; at least 55 should load
        assert len(_rule_set().rules) >= 55

    def test_all_rules_have_rule_id(self):
        for r in _rule_set().rules:
            assert r.rule_id, f"rule missing rule_id: {r}"

    def test_all_rules_have_embedding_text(self):
        for r in _rule_set().rules:
            assert r.embedding_text, f"rule {r.rule_id} has empty embedding_text"

    def test_hard_rules_exist(self):
        hard = [r for r in _rule_set().rules if r.severity == Severity.HARD]
        assert len(hard) > 10

    def test_advisory_rules_exist(self):
        advisory = [r for r in _rule_set().rules if r.severity == Severity.ADVISORY]
        assert len(advisory) > 0

    def test_vastu_rules_exist(self):
        vastu = [r for r in _rule_set().rules if r.category == RuleCategory.VASTU]
        assert len(vastu) >= 5

    def test_by_category(self):
        rs = _rule_set()
        area_rules = rs.by_category(RuleCategory.AREA)
        assert len(area_rules) >= 10

    def test_setback_rules_have_conditions(self):
        rs = _rule_set()
        setback_rules = rs.by_category(RuleCategory.SETBACK)
        # Road-width-dependent rules must have conditions
        road_dependent = [r for r in setback_rules if "road_width_max" in r.conditions
                          or "road_width_min" in r.conditions]
        assert len(road_dependent) >= 3


# ---------------------------------------------------------------------------
# 2. Keyword retriever
# ---------------------------------------------------------------------------

class TestKeywordRetriever:
    def test_bedroom_area_search(self):
        rs = _rule_set()
        retriever = RuleRetriever.from_rule_set(rs)
        results = retriever.search("bedroom minimum area Nepal", n_results=5)
        assert len(results) > 0
        rule_ids = [r.rule_id for r in results]
        assert any("AREA" in rid for rid in rule_ids)

    def test_setback_search(self):
        rs = _rule_set()
        retriever = RuleRetriever.from_rule_set(rs)
        results = retriever.search("front setback road width", n_results=5)
        assert len(results) > 0

    def test_category_filter(self):
        rs = _rule_set()
        retriever = RuleRetriever.from_rule_set(rs)
        results = retriever.search("Nepal building", n_results=20, category=RuleCategory.AREA)
        assert all(r.category == RuleCategory.AREA for r in results)

    def test_get_by_room_type(self):
        rs = _rule_set()
        retriever = RuleRetriever.from_rule_set(rs)
        bedroom_rules = retriever.get_by_room_type("bedroom")
        assert len(bedroom_rules) > 0


# ---------------------------------------------------------------------------
# 3. Area rule violations
# ---------------------------------------------------------------------------

class TestAreaRules:
    def test_undersized_master_bedroom_flagged(self):
        # Master bedroom must be >= 10.5 sqm; give it 8.0 sqm (2.5×3.2)
        rooms = [_room(RoomType.MASTER_BEDROOM, width=2.5, depth=3.2)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        assert not report.compliant
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_AREA_101" in ids

    def test_conforming_master_bedroom_no_violation(self):
        # 3.5 × 3.5 = 12.25 sqm — above 10.5 sqm minimum
        rooms = [_room(RoomType.MASTER_BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        area_viols = [v for v in report.violations if v.rule_id == "NP_KTM_AREA_101"]
        assert len(area_viols) == 0

    def test_undersized_bedroom_flagged(self):
        # Bedroom must be >= 9.5 sqm; give it 8.0 sqm
        rooms = [_room(RoomType.BEDROOM, width=2.5, depth=3.2)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_AREA_102" in ids

    def test_undersized_kitchen_flagged(self):
        # Kitchen must be >= 5.0 sqm; give it 3.0 sqm
        rooms = [_room(RoomType.KITCHEN, width=1.5, depth=2.0)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_AREA_105" in ids

    def test_undersized_bathroom_flagged(self):
        rooms = [_room(RoomType.BATHROOM, width=1.0, depth=1.5)]  # 1.5 sqm < 2.5 sqm
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_AREA_106" in ids

    def test_actual_value_reported(self):
        rooms = [_room(RoomType.BEDROOM, width=2.5, depth=3.0)]  # 7.5 sqm
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        v = next((x for x in report.violations if x.rule_id == "NP_KTM_AREA_102"), None)
        assert v is not None
        assert abs(v.actual_value - 7.5) < 0.01
        assert v.required_value == 9.5


# ---------------------------------------------------------------------------
# 4. Dimension rule violations
# ---------------------------------------------------------------------------

class TestDimensionRules:
    def test_narrow_master_bedroom_flagged(self):
        # Master bedroom shorter side must be >= 3.0 m; 2.5 × 5.0 has shorter = 2.5
        rooms = [_room(RoomType.MASTER_BEDROOM, width=2.5, depth=5.0)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_DIM_102" in ids

    def test_narrow_bedroom_flagged(self):
        # Bedroom shorter side must be >= 2.7 m; 2.5 × 4.0 has shorter = 2.5
        rooms = [_room(RoomType.BEDROOM, width=2.5, depth=4.0)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_DIM_103" in ids

    def test_conforming_bedroom_dimension_no_violation(self):
        # 2.8 × 3.5 m — shorter = 2.8 >= 2.7 m
        rooms = [_room(RoomType.BEDROOM, width=2.8, depth=3.5)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        dim_viols = [v for v in report.violations if v.rule_id == "NP_KTM_DIM_103"]
        assert len(dim_viols) == 0


# ---------------------------------------------------------------------------
# 5. Ground coverage violations
# ---------------------------------------------------------------------------

class TestCoverageRules:
    def test_excessive_coverage_flagged(self):
        # Plot = 10 × 10 = 100 sqm. Fill 70 sqm (70%) → exceeds 60%
        rooms = [_room(RoomType.LIVING_ROOM, width=8.5, depth=8.3)]  # ~70.6 sqm
        b = _building(rooms, plot_width=10.0, plot_depth=10.0)
        report = check_compliance(b, plot_area_sqm=100.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_COV_101" in ids

    def test_coverage_metric_computed(self):
        rooms = [_room(RoomType.LIVING_ROOM, width=8.0, depth=8.0)]  # 64 sqm
        b = _building(rooms, plot_width=10.0, plot_depth=10.0)
        report = check_compliance(b, plot_area_sqm=100.0, rules=_rule_set().rules)
        assert report.coverage_pct is not None
        assert abs(report.coverage_pct - 64.0) < 1.0

    def test_acceptable_coverage_no_violation(self):
        # 50 sqm on 100 sqm plot = 50% < 60%
        rooms = [_room(RoomType.LIVING_ROOM, width=7.0, depth=7.0)]  # 49 sqm
        b = _building(rooms, plot_width=10.0, plot_depth=10.0)
        report = check_compliance(b, plot_area_sqm=100.0, rules=_rule_set().rules)
        cov_viols = [v for v in report.violations if v.rule_id == "NP_KTM_COV_101"]
        assert len(cov_viols) == 0


# ---------------------------------------------------------------------------
# 6. FAR violations
# ---------------------------------------------------------------------------

class TestFARRules:
    def test_far_exceeded_flagged_narrow_road(self):
        # Road 5m → max FAR = 1.5
        # Plot 100 sqm; put 200 sqm of rooms (FAR = 2.0 > 1.5)
        r1 = _room(RoomType.BEDROOM, width=7.0, depth=7.0, floor=1)   # 49 sqm
        r2 = _room(RoomType.BEDROOM, width=7.0, depth=7.0, floor=1)   # 49 sqm (total 98)
        # Need 150+ sqm on 100 sqm plot
        r3 = _room(RoomType.LIVING_ROOM, width=7.0, depth=8.0, floor=1)  # 56 sqm
        b = _building([r1, r2, r3], plot_width=10.0, plot_depth=10.0)
        report = check_compliance(
            b, plot_area_sqm=100.0, rules=_rule_set().rules, road_width_m=5.0
        )
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_FAR_101" in ids

    def test_far_metric_computed(self):
        rooms = [_room(RoomType.LIVING_ROOM, width=8.0, depth=8.0)]  # 64 sqm
        b = _building(rooms, plot_width=10.0, plot_depth=10.0)
        report = check_compliance(b, plot_area_sqm=100.0, rules=_rule_set().rules, road_width_m=7.0)
        assert report.far_actual is not None
        assert abs(report.far_actual - 0.64) < 0.01

    def test_far_rule_skipped_without_road_width(self):
        """FAR rules have road_width conditions; no road_width → rules skipped."""
        rooms = [_room(RoomType.BEDROOM, width=7.0, depth=7.0)]
        b = _building(rooms)
        report = check_compliance(
            b, plot_area_sqm=100.0, rules=_rule_set().rules, road_width_m=None
        )
        far_viols = [v for v in report.violations
                     if v.rule_id.startswith("NP_KTM_FAR")]
        assert len(far_viols) == 0  # Skipped, not violated


# ---------------------------------------------------------------------------
# 7. Setback violations
# ---------------------------------------------------------------------------

class TestSetbackRules:
    def test_insufficient_front_setback_flagged(self):
        # Road 7m → required front setback = 1.5 m; give 0.8 m
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, setback_front=0.8)
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules, road_width_m=7.0
        )
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_SETB_102" in ids

    def test_correct_front_setback_no_violation(self):
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, setback_front=2.0)
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules, road_width_m=7.0
        )
        setb_viols = [v for v in report.violations if v.rule_id == "NP_KTM_SETB_102"]
        assert len(setb_viols) == 0

    def test_insufficient_rear_setback_flagged(self):
        # Plot > 100 sqm, rear must be >= 1.5 m; give 0.5 m
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, setback_rear=0.5)
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules
        )
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_SETB_106" in ids

    def test_insufficient_side_setback_flagged(self):
        # ≤3 floors, side must be >= 1.0 m; give 0.5 m on left
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, setback_left=0.5, setback_right=1.5, num_floors=2)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_SETB_107" in ids


# ---------------------------------------------------------------------------
# 8. Floor height violations
# ---------------------------------------------------------------------------

class TestFloorHeightRules:
    def test_low_ceiling_flagged(self):
        # Habitable rooms need >= 2.6 m; give 2.2 m
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, floor_height=2.2)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_HGT_101" in ids

    def test_adequate_ceiling_no_violation(self):
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms, floor_height=3.0)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        hgt_viols = [v for v in report.violations if v.rule_id == "NP_KTM_HGT_101"]
        assert len(hgt_viols) == 0


# ---------------------------------------------------------------------------
# 9. Window area violations
# ---------------------------------------------------------------------------

class TestWindowAreaRules:
    def test_insufficient_window_area_flagged(self):
        # Bedroom 3.5 × 3.5 = 12.25 sqm; needs 10% = 1.225 sqm windows
        # Give one tiny window: 0.5 × 0.5 = 0.25 sqm
        tiny_window = Window(
            wall_face=WallFace.NORTH,
            position_along_wall=1.0,
            width=0.5,
            height=0.5,
        )
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5, windows=[tiny_window])]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_OPN_101" in ids

    def test_adequate_window_area_no_violation(self):
        # 3.5 × 3.5 room; needs 1.225 sqm windows; give 1.2 × 1.2 = 1.44 sqm
        good_window = Window(
            wall_face=WallFace.NORTH,
            position_along_wall=1.0,
            width=1.2,
            height=1.2,
        )
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5, windows=[good_window])]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        win_viols = [v for v in report.violations if v.rule_id == "NP_KTM_OPN_101"]
        assert len(win_viols) == 0

    def test_room_without_windows_skipped(self):
        """Windows not defined → rule skipped (can't penalise missing data)."""
        rooms = [_room(RoomType.BEDROOM, width=3.5, depth=3.5, windows=[])]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        win_viols = [v for v in report.violations if v.rule_id == "NP_KTM_OPN_101"]
        assert len(win_viols) == 0


# ---------------------------------------------------------------------------
# 10. Staircase width
# ---------------------------------------------------------------------------

class TestStaircaseRules:
    def test_narrow_staircase_flagged(self):
        # Stair must be >= 0.9 m wide; give 0.7 m
        rooms = [_room(RoomType.STAIRCASE, width=0.7, depth=3.0)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        ids = [v.rule_id for v in report.violations]
        assert "NP_KTM_STAIR_101" in ids

    def test_conforming_staircase_no_violation(self):
        rooms = [_room(RoomType.STAIRCASE, width=1.2, depth=3.0)]
        b = _building(rooms)
        report = check_compliance(b, plot_area_sqm=180.0, rules=_rule_set().rules)
        stair_viols = [v for v in report.violations if v.rule_id == "NP_KTM_STAIR_101"]
        assert len(stair_viols) == 0


# ---------------------------------------------------------------------------
# 11. Vastu rules (advisory only)
# ---------------------------------------------------------------------------

class TestVastuRules:
    def test_vastu_skipped_when_disabled(self):
        rooms = [_room(RoomType.MASTER_BEDROOM, width=3.5, depth=3.5)]
        b = _building(rooms)
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules, vastu_enabled=False
        )
        vastu_adv = [a for a in report.advisories if "VASTU" in a.rule_id]
        assert len(vastu_adv) == 0

    def test_vastu_advisory_issued_when_enabled(self):
        # Put master bedroom in northeast (x=12, y=9 on 15×12 plot) — NOT southwest
        room = RoomLayout(
            room_id="mbr",
            room_type=RoomType.MASTER_BEDROOM,
            name="Master Bedroom",
            floor=1,
            bounds=Rect2D(x=11.0, y=9.0, width=3.0, depth=2.5),
        )
        b = _building([room])
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules, vastu_enabled=True
        )
        vastu_adv = [a for a in report.advisories if "VASTU" in a.rule_id]
        assert len(vastu_adv) > 0

    def test_vastu_correct_placement_no_advisory(self):
        # Master bedroom in southwest: x < 7.5, y < 6 on 15×12 plot
        room = RoomLayout(
            room_id="mbr",
            room_type=RoomType.MASTER_BEDROOM,
            name="Master Bedroom",
            floor=1,
            bounds=Rect2D(x=1.5, y=1.5, width=3.5, depth=3.5),
        )
        b = _building([room])
        report = check_compliance(
            b, plot_area_sqm=180.0, rules=_rule_set().rules, vastu_enabled=True
        )
        mbr_vastu = [a for a in report.advisories if a.rule_id == "NP_KTM_VASTU_101"]
        assert len(mbr_vastu) == 0


# ---------------------------------------------------------------------------
# 12. Compliant design baseline
# ---------------------------------------------------------------------------

class TestCompliantDesign:
    """A well-designed 3BHK should pass all hard rules."""

    def _make_3bhk(self) -> tuple[BuildingDesign, float]:
        rooms = [
            _room(RoomType.MASTER_BEDROOM, width=3.6, depth=3.2),   # 11.52 sqm ✓
            _room(RoomType.BEDROOM,        width=3.0, depth=3.2),   # 9.6 sqm ✓
            _room(RoomType.BEDROOM,        width=3.0, depth=3.2),   # 9.6 sqm ✓
            _room(RoomType.LIVING_ROOM,    width=4.0, depth=3.5),   # 14.0 sqm ✓
            _room(RoomType.KITCHEN,        width=2.6, depth=2.4),   # 6.24 sqm ✓ (dim 2.4 ✓)
            _room(RoomType.BATHROOM,       width=1.8, depth=1.5),   # 2.7 sqm ✓
            _room(RoomType.TOILET,         width=1.2, depth=1.2),   # 1.44 sqm ✓
            _room(RoomType.STAIRCASE,      width=1.5, depth=3.0),   # 4.5 sqm ✓ (width 1.5 ✓)
        ]
        # Plot 15 × 12 = 180 sqm; setbacks 1.5/1.5/1.0/1.0
        building = _building(
            rooms,
            plot_width=15.0,
            plot_depth=12.0,
            setback_front=2.0,
            setback_rear=1.5,
            setback_left=1.5,
            setback_right=1.5,
            num_floors=2,
            floor_height=3.0,
        )
        return building, 180.0

    def test_no_hard_violations(self):
        b, plot_area = self._make_3bhk()
        report = check_compliance(
            b, plot_area_sqm=plot_area, rules=_rule_set().rules, road_width_m=7.0
        )
        assert report.compliant, (
            f"Expected compliant design. Violations:\n"
            + "\n".join(f"  {v.rule_id}: {v.message}" for v in report.violations)
        )

    def test_coverage_within_limit(self):
        b, plot_area = self._make_3bhk()
        report = check_compliance(b, plot_area_sqm=plot_area, rules=_rule_set().rules)
        assert report.coverage_pct is not None
        assert report.coverage_pct <= 60.0

    def test_far_within_limit_road_7m(self):
        b, plot_area = self._make_3bhk()
        report = check_compliance(
            b, plot_area_sqm=plot_area, rules=_rule_set().rules, road_width_m=7.0
        )
        assert report.far_actual is not None
        assert report.far_actual <= 2.0  # road 7m → FAR max 2.0

    def test_report_has_metrics(self):
        b, plot_area = self._make_3bhk()
        report = check_compliance(b, plot_area_sqm=plot_area, rules=_rule_set().rules)
        assert report.total_built_sqm is not None
        assert report.total_built_sqm > 0
        assert report.rules_checked > 0
