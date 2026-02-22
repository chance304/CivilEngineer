"""
Unit tests for staircase geometry sizing.

Tests _compute_staircase_dims() and StaircaseSpec propagation through the
constraint solver pipeline.
"""

from __future__ import annotations

import math

import pytest

from civilengineer.reasoning_engine.constraint_solver import (
    _compute_staircase_dims,
    solve_layout,
)
from civilengineer.schemas.design import (
    DesignRequirements,
    Rect2D,
    RoomRequirement,
    RoomType,
    StaircaseSpec,
)


# ---------------------------------------------------------------------------
# _compute_staircase_dims
# ---------------------------------------------------------------------------


def test_staircase_dims_riser_count_3m():
    """For 3.0m floor height: ceil(3000/175) = 18 risers."""
    w, d, spec = _compute_staircase_dims(floor_height_m=3.0)
    assert spec.num_risers == 18
    assert spec.riser_height_mm == pytest.approx(175.0)
    assert spec.tread_depth_mm == pytest.approx(280.0)


def test_staircase_dims_enclosure_width():
    """U-turn enclosure width = 2 × 1.0m clear + 0.23m wall = 2.23m."""
    w, d, spec = _compute_staircase_dims(floor_height_m=3.0)
    assert w == pytest.approx(2.23, abs=0.02)


def test_staircase_dims_enclosure_depth_3m():
    """
    For 3.0m: 18 risers → 9 per half → flight_run = 9 × 0.28 = 2.52m
    enclosure_depth = 2.52 + 1.0 (landing) = 3.52m
    """
    w, d, spec = _compute_staircase_dims(floor_height_m=3.0)
    assert d == pytest.approx(3.52, abs=0.05)


def test_staircase_dims_larger_than_old_default():
    """New computed dims must exceed old hardcoded (2.0 × 2.4)."""
    w, d, spec = _compute_staircase_dims(floor_height_m=3.0)
    assert w > 2.0
    assert d > 2.4


def test_staircase_dims_different_height():
    """Test with 2.7m floor height (common in older buildings)."""
    w, d, spec = _compute_staircase_dims(floor_height_m=2.7)
    # ceil(2700/175) = 16 risers, 8 per half, flight_run = 8*0.28 = 2.24m
    assert spec.num_risers == math.ceil(2700 / 175)
    assert d == pytest.approx(spec.landing_depth_m + math.ceil(spec.num_risers / 2) * 0.28, abs=0.05)


def test_staircase_spec_type():
    """StaircaseSpec must have stair_type='u_turn' and headroom_m=2.0."""
    _, _, spec = _compute_staircase_dims()
    assert spec.stair_type == "u_turn"
    assert spec.headroom_m == pytest.approx(2.0)
    assert spec.clear_width_m == pytest.approx(1.0)
    assert spec.landing_depth_m == pytest.approx(1.0)


def test_staircase_spec_is_staircase_spec_instance():
    """Return type must be StaircaseSpec."""
    _, _, spec = _compute_staircase_dims()
    assert isinstance(spec, StaircaseSpec)


# ---------------------------------------------------------------------------
# StaircaseSpec propagation through solve_layout
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_requirements():
    return DesignRequirements(
        project_id="test",
        num_floors=1,
        rooms=[
            RoomRequirement(room_type=RoomType.LIVING_ROOM),
            RoomRequirement(room_type=RoomType.STAIRCASE),
        ],
    )


@pytest.fixture()
def zone():
    return Rect2D(x=3.0, y=3.0, width=15.0, depth=18.0)


def test_solve_staircase_has_spec(simple_requirements, zone):
    """PlacedRoom for staircase must carry staircase_spec."""
    result = solve_layout(simple_requirements, zone, [])
    stair_rooms = [r for r in result.placed_rooms if r.room_req.room_type == RoomType.STAIRCASE]
    assert stair_rooms, "No staircase room placed"
    for sr in stair_rooms:
        assert sr.staircase_spec is not None
        assert isinstance(sr.staircase_spec, StaircaseSpec)


def test_solve_staircase_dimensions_correct(simple_requirements, zone):
    """Staircase enclosure dimensions match _compute_staircase_dims()."""
    result = solve_layout(simple_requirements, zone, [])
    stair_rooms = [r for r in result.placed_rooms if r.room_req.room_type == RoomType.STAIRCASE]
    assert stair_rooms
    sr = stair_rooms[0]
    expected_w, expected_d, _ = _compute_staircase_dims(3.0)
    # Actual enclosure must be at least as large as computed minimum
    assert sr.width >= expected_w - 0.05 or sr.depth >= expected_w - 0.05


def test_non_staircase_has_no_spec(simple_requirements, zone):
    """Non-staircase rooms must not have staircase_spec set."""
    result = solve_layout(simple_requirements, zone, [])
    non_stair = [r for r in result.placed_rooms if r.room_req.room_type != RoomType.STAIRCASE]
    for room in non_stair:
        assert room.staircase_spec is None
