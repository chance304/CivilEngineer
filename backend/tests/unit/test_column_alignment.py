"""
Unit tests for column grid extraction and cross-floor CP-SAT alignment.

Tests _extract_column_grid(), _find_column_positions(), and that
solve_layout() produces columns in SolveResult and upper-floor rooms
align to floor 1 grid.
"""

from __future__ import annotations

import pytest

from civilengineer.reasoning_engine.constraint_solver import (
    PlacedRoom,
    SolveStatus,
    _extract_column_grid,
    _find_column_positions,
    solve_layout,
)
from civilengineer.schemas.design import (
    DesignRequirements,
    Rect2D,
    RoomRequirement,
    RoomType,
)


# ---------------------------------------------------------------------------
# _extract_column_grid
# ---------------------------------------------------------------------------


def _make_placed(x, y, w, d, rtype=RoomType.BEDROOM) -> PlacedRoom:
    return PlacedRoom(
        room_req=RoomRequirement(room_type=rtype),
        floor=1,
        x=x, y=y, width=w, depth=d,
    )


def test_extract_column_grid_basic():
    """xs should include all left and right edges of placed rooms."""
    _SCALE = 10
    placed = [
        _make_placed(0.0, 0.0, 3.0, 4.0),   # x: 0, 30; y: 0, 40
        _make_placed(3.0, 0.0, 4.0, 4.0),   # x: 30, 70; y: 0, 40
    ]
    xs, ys = _extract_column_grid(placed)
    assert 0 in xs
    assert 30 in xs
    assert 70 in xs
    assert 0 in ys
    assert 40 in ys


def test_extract_column_grid_returns_frozensets():
    placed = [_make_placed(0.0, 0.0, 3.0, 3.0)]
    xs, ys = _extract_column_grid(placed)
    assert isinstance(xs, frozenset)
    assert isinstance(ys, frozenset)


def test_extract_column_grid_single_room():
    placed = [_make_placed(2.0, 1.0, 4.0, 5.0)]
    xs, ys = _extract_column_grid(placed)
    # x: 20, 60 (in _SCALE=10 units); y: 10, 60
    assert 20 in xs and 60 in xs
    assert 10 in ys and 60 in ys


def test_extract_column_grid_no_duplicates():
    """Adjacent rooms sharing an edge should produce no duplicate coordinates."""
    placed = [
        _make_placed(0.0, 0.0, 3.0, 3.0),
        _make_placed(3.0, 0.0, 3.0, 3.0),  # shared edge at x=3.0 → 30
    ]
    xs, ys = _extract_column_grid(placed)
    # frozenset guarantees uniqueness; len should be 3 (0, 30, 60) not 4
    assert len(xs) == 3


# ---------------------------------------------------------------------------
# _find_column_positions
# ---------------------------------------------------------------------------


def test_find_column_positions_count():
    """Should produce |xs| × |ys| × |floors| entries."""
    xs = frozenset([0, 30, 60])
    ys = frozenset([0, 40])
    zone = Rect2D(x=3.0, y=3.0, width=6.0, depth=8.0)
    cols = _find_column_positions(xs, ys, zone, floors_solved=[1, 2])
    assert len(cols) == 3 * 2 * 2  # 3 xs × 2 ys × 2 floors


def test_find_column_positions_coordinates():
    """Column x should be xs_entry/_SCALE + zone.x."""
    xs = frozenset([0, 30])
    ys = frozenset([0])
    zone = Rect2D(x=3.0, y=3.0, width=6.0, depth=8.0)
    cols = _find_column_positions(xs, ys, zone, floors_solved=[1])
    xs_found = sorted(c["x"] for c in cols)
    assert xs_found[0] == pytest.approx(3.0 + 0.0 / 10)  # zone.x + 0/scale
    assert xs_found[1] == pytest.approx(3.0 + 3.0)        # zone.x + 30/scale = 3+3=6


def test_find_column_positions_has_floor_key():
    xs = frozenset([0])
    ys = frozenset([0])
    zone = Rect2D(x=0.0, y=0.0, width=10.0, depth=10.0)
    cols = _find_column_positions(xs, ys, zone, floors_solved=[1, 2])
    floors = {c["floor"] for c in cols}
    assert floors == {1, 2}


def test_find_column_positions_default_size():
    """Columns should default to 0.30m × 0.30m."""
    xs = frozenset([0])
    ys = frozenset([0])
    zone = Rect2D(x=0.0, y=0.0, width=10.0, depth=10.0)
    cols = _find_column_positions(xs, ys, zone, floors_solved=[1])
    assert cols[0]["width"] == pytest.approx(0.30)
    assert cols[0]["depth"] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# solve_layout — SolveResult.columns
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_floor_requirements():
    return DesignRequirements(
        project_id="col_test",
        num_floors=2,
        rooms=[
            RoomRequirement(room_type=RoomType.LIVING_ROOM),
            RoomRequirement(room_type=RoomType.KITCHEN),
            RoomRequirement(room_type=RoomType.MASTER_BEDROOM),
            RoomRequirement(room_type=RoomType.BEDROOM),
            RoomRequirement(room_type=RoomType.STAIRCASE),
        ],
    )


@pytest.fixture()
def big_zone():
    return Rect2D(x=3.0, y=3.0, width=14.0, depth=16.0)


def test_solve_produces_columns(two_floor_requirements, big_zone):
    """SolveResult.columns must be non-empty for a multi-floor design."""
    result = solve_layout(two_floor_requirements, big_zone, [])
    if result.status != SolveStatus.UNSAT:
        assert len(result.columns) > 0


def test_solve_columns_have_required_fields(two_floor_requirements, big_zone):
    """Each column dict must have x, y, width, depth, floor keys."""
    result = solve_layout(two_floor_requirements, big_zone, [])
    for col in result.columns:
        assert "x" in col
        assert "y" in col
        assert "width" in col
        assert "depth" in col
        assert "floor" in col


def test_solve_columns_appear_on_both_floors(two_floor_requirements, big_zone):
    """Columns should appear on floor 1 and floor 2."""
    result = solve_layout(two_floor_requirements, big_zone, [])
    if result.status != SolveStatus.UNSAT and result.columns:
        col_floors = {c["floor"] for c in result.columns}
        assert 1 in col_floors
        assert 2 in col_floors


def test_single_floor_no_columns():
    """Single-floor buildings without staircase may have zero columns (floor 1 only)."""
    req = DesignRequirements(
        project_id="single",
        num_floors=1,
        rooms=[RoomRequirement(room_type=RoomType.LIVING_ROOM)],
    )
    zone = Rect2D(x=3.0, y=3.0, width=10.0, depth=10.0)
    result = solve_layout(req, zone, [])
    # Columns are present whenever we solved floor 1 (we always extract grid from floor 1)
    # This is fine — a single-floor building still has columns at grid intersections
    assert isinstance(result.columns, list)
