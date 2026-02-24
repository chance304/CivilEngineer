"""
Unit tests for CostEstimator — finish overrides, tier comparison, multipliers.
"""

from __future__ import annotations

import pytest

from civilengineer.output_layer.cost_estimator import (
    CostEstimate,
    CostEstimator,
    RoomCost,
    _CEILING_MULT,
    _FLOORING_MULT,
    _WALL_PAINT_MULT,
)
from civilengineer.schemas.design import (
    BuildingDesign,
    FinishSpec,
    FloorFinish,
    FloorPlan,
    Rect2D,
    RoomLayout,
    RoomType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_room(
    room_id: str,
    room_type: RoomType,
    width: float = 4.0,
    depth: float = 4.0,
    floor: int = 1,
) -> RoomLayout:
    return RoomLayout(
        room_id=room_id,
        room_type=room_type,
        name=room_type.value,
        floor=floor,
        bounds=Rect2D(x=0, y=0, width=width, depth=depth),
    )


def _make_building(rooms: list[RoomLayout], num_floors: int = 1) -> BuildingDesign:
    fp = FloorPlan(
        floor=1,
        buildable_zone=Rect2D(x=0, y=0, width=20, depth=20),
        rooms=rooms,
    )
    return BuildingDesign(
        design_id="d1",
        project_id="p1",
        num_floors=num_floors,
        plot_width=20.0,
        plot_depth=20.0,
        floor_plans=[fp],
    )


# ---------------------------------------------------------------------------
# Basic estimation (no overrides)
# ---------------------------------------------------------------------------


class TestCostEstimatorBasic:
    def test_returns_cost_estimate(self):
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator(material_grade="standard").estimate(building)
        assert isinstance(est, CostEstimate)

    def test_total_area_correct(self):
        building = _make_building([
            _make_room("r1", RoomType.BEDROOM, width=4, depth=4),
            _make_room("r2", RoomType.KITCHEN, width=3, depth=3),
        ])
        est = CostEstimator().estimate(building)
        assert abs(est.total_area_sqm - (16.0 + 9.0)) < 0.01

    def test_total_cost_positive(self):
        building = _make_building([_make_room("r1", RoomType.LIVING_ROOM)])
        est = CostEstimator().estimate(building)
        assert est.total_cost_inr > 0

    def test_cost_per_sqm_consistent(self):
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator().estimate(building)
        expected = round(est.total_cost_inr / est.total_area_sqm, 0)
        assert abs(est.cost_per_sqm_inr - expected) <= 1.0

    def test_grade_ordering(self):
        """Premium > standard > basic for identical building."""
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        basic    = CostEstimator("basic").estimate(building).total_cost_inr
        standard = CostEstimator("standard").estimate(building).total_cost_inr
        premium  = CostEstimator("premium").estimate(building).total_cost_inr
        assert basic < standard < premium

    def test_room_breakdown_populated(self):
        building = _make_building([
            _make_room("r1", RoomType.BEDROOM),
            _make_room("r2", RoomType.BATHROOM),
        ])
        est = CostEstimator().estimate(building)
        assert len(est.room_breakdown) == 2
        ids = {r.room_id for r in est.room_breakdown}
        assert ids == {"r1", "r2"}

    def test_type_breakdown_aggregated(self):
        building = _make_building([
            _make_room("r1", RoomType.BEDROOM),
            _make_room("r2", RoomType.BEDROOM),
        ])
        est = CostEstimator().estimate(building)
        assert "bedroom" in est.type_breakdown
        assert est.type_breakdown["bedroom"] > 0

    def test_zero_area_room_skipped(self):
        building = _make_building([
            _make_room("r1", RoomType.BEDROOM, width=0, depth=0),
            _make_room("r2", RoomType.KITCHEN),
        ])
        est = CostEstimator().estimate(building)
        assert len(est.room_breakdown) == 1  # only kitchen

    def test_invalid_grade_raises(self):
        with pytest.raises(ValueError):
            CostEstimator(material_grade="gold")  # type: ignore[arg-type]

    def test_formatted_total_lakh(self):
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator("basic").estimate(building)
        # Small building → result in lakhs
        fmt = est.formatted_total()
        assert "L" in fmt or "Cr" in fmt   # just check it runs


# ---------------------------------------------------------------------------
# Tier comparison
# ---------------------------------------------------------------------------


class TestTierComparison:
    def test_tier_comparison_has_three_grades(self):
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator("standard").estimate(building)
        assert set(est.tier_comparison.keys()) == {"basic", "standard", "premium"}

    def test_tier_comparison_ordered(self):
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator("standard").estimate(building)
        tc = est.tier_comparison
        assert tc["basic"] < tc["standard"] < tc["premium"]

    def test_tier_comparison_standard_close_to_actual(self):
        """When grade=standard and no overrides, tier[standard] ≈ total_cost."""
        building = _make_building([_make_room("r1", RoomType.BEDROOM)])
        est = CostEstimator("standard").estimate(building)
        # They should match since no finish overrides
        assert abs(est.tier_comparison["standard"] - est.total_cost_inr) < 1.0


# ---------------------------------------------------------------------------
# Finish multipliers
# ---------------------------------------------------------------------------


class TestFinishMultipliers:
    def test_flooring_mult_table_has_all_values(self):
        for ff in FloorFinish:
            assert ff in _FLOORING_MULT

    def test_tile_is_baseline(self):
        assert _FLOORING_MULT[FloorFinish.TILE] == 1.0

    def test_marble_most_expensive(self):
        assert _FLOORING_MULT[FloorFinish.MARBLE] == max(_FLOORING_MULT.values())

    def test_concrete_cheapest(self):
        assert _FLOORING_MULT[FloorFinish.CONCRETE] == min(_FLOORING_MULT.values())

    def test_wall_paint_standard_baseline(self):
        assert _WALL_PAINT_MULT["standard"] == 1.0

    def test_ceiling_plaster_baseline(self):
        assert _CEILING_MULT["plaster"] == 1.0


# ---------------------------------------------------------------------------
# Finish overrides applied correctly
# ---------------------------------------------------------------------------


class TestFinishOverrides:
    def _estimator_with_override(
        self, grade: str = "standard", flooring: FloorFinish = FloorFinish.MARBLE
    ) -> tuple[CostEstimator, CostEstimator]:
        spec = FinishSpec(flooring=flooring)
        with_override    = CostEstimator(material_grade=grade, finish_overrides={"bedroom": spec})  # type: ignore[arg-type]
        without_override = CostEstimator(material_grade=grade)
        return with_override, without_override

    def _building_with_bedroom(self) -> BuildingDesign:
        return _make_building([_make_room("r1", RoomType.BEDROOM)])

    def test_marble_override_increases_finish_cost(self):
        with_ov, without = self._estimator_with_override(flooring=FloorFinish.MARBLE)
        building = self._building_with_bedroom()
        assert with_ov.estimate(building).finish_cost > without.estimate(building).finish_cost

    def test_concrete_override_decreases_finish_cost(self):
        with_ov, without = self._estimator_with_override(flooring=FloorFinish.CONCRETE)
        building = self._building_with_bedroom()
        assert with_ov.estimate(building).finish_cost < without.estimate(building).finish_cost

    def test_tile_override_same_as_no_override(self):
        """TILE has multiplier 1.0, so finish cost should not change."""
        spec = FinishSpec(flooring=FloorFinish.TILE, wall_paint="standard", ceiling="plaster")
        with_ov  = CostEstimator("standard", finish_overrides={"bedroom": spec})
        without  = CostEstimator("standard")
        building = self._building_with_bedroom()
        assert abs(
            with_ov.estimate(building).finish_cost - without.estimate(building).finish_cost
        ) < 1.0

    def test_flooring_used_set_on_room_cost(self):
        spec = FinishSpec(flooring=FloorFinish.GRANITE)
        est  = CostEstimator("standard", finish_overrides={"bedroom": spec}).estimate(
            self._building_with_bedroom()
        )
        rc = est.room_breakdown[0]
        assert rc.flooring_used == "granite"

    def test_no_override_flooring_used_is_none(self):
        est = CostEstimator("standard").estimate(self._building_with_bedroom())
        assert est.room_breakdown[0].flooring_used is None

    def test_override_does_not_affect_structure_cost(self):
        """Structure cost is independent of finish overrides."""
        spec = FinishSpec(flooring=FloorFinish.MARBLE)
        with_ov  = CostEstimator("standard", finish_overrides={"bedroom": spec})
        without  = CostEstimator("standard")
        building = self._building_with_bedroom()
        assert with_ov.estimate(building).structure_cost == without.estimate(building).structure_cost

    def test_override_only_affects_matching_room_type(self):
        """Kitchen override should not change bedroom finish cost."""
        building = _make_building([
            _make_room("r1", RoomType.BEDROOM),
            _make_room("r2", RoomType.KITCHEN),
        ])
        spec = FinishSpec(flooring=FloorFinish.MARBLE)
        with_ov  = CostEstimator("standard", finish_overrides={"kitchen": spec})
        without  = CostEstimator("standard")

        def _room_finish(est, room_id):
            return next(r.finish_cost for r in est.room_breakdown if r.room_id == room_id)

        # bedroom unchanged
        assert _room_finish(with_ov.estimate(building), "r1") == \
               _room_finish(without.estimate(building), "r1")
        # kitchen changed
        assert _room_finish(with_ov.estimate(building), "r2") > \
               _room_finish(without.estimate(building), "r2")

    def test_none_overrides_treated_as_empty(self):
        est = CostEstimator("standard", finish_overrides=None).estimate(
            self._building_with_bedroom()
        )
        assert isinstance(est, CostEstimate)
        assert est.room_breakdown[0].flooring_used is None

    def test_combined_wall_and_ceiling_multiplier(self):
        """premium wall + wood_panel ceiling → multiplier > 1."""
        spec = FinishSpec(
            flooring=FloorFinish.TILE,  # mult=1.0
            wall_paint="premium",        # mult=1.4
            ceiling="wood_panel",        # mult=2.5
        )
        est_with = CostEstimator("standard", finish_overrides={"bedroom": spec})
        est_base = CostEstimator("standard")
        building = self._building_with_bedroom()
        assert est_with.estimate(building).finish_cost > est_base.estimate(building).finish_cost
