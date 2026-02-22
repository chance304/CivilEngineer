"""
Unit tests for cross-floor load-bearing wall detection.

Tests build_walls_cross_floor() and _wall_supports_room() from wall_builder.py.
"""

from __future__ import annotations

import pytest

from civilengineer.geometry_engine.wall_builder import (
    build_walls,
    build_walls_cross_floor,
    _wall_supports_room,
)
from civilengineer.schemas.design import (
    FloorPlan,
    Point2D,
    Rect2D,
    RoomLayout,
    RoomType,
    WallSegment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_room(x, y, w, d, rtype=RoomType.BEDROOM, floor=1) -> RoomLayout:
    return RoomLayout(
        room_id=f"R{floor}_{rtype.value}",
        room_type=rtype,
        name=rtype.value.replace("_", " ").title(),
        floor=floor,
        bounds=Rect2D(x=x, y=y, width=w, depth=d),
    )


def _make_wall(x1, y1, x2, y2, load_bearing=False) -> WallSegment:
    return WallSegment(
        start=Point2D(x=x1, y=y1),
        end=Point2D(x=x2, y=y2),
        thickness=0.23,
        is_load_bearing=load_bearing,
    )


def _make_floor(rooms, floor=1, zone_x=3.0, zone_y=3.0, zone_w=12.0, zone_d=15.0) -> FloorPlan:
    fp = FloorPlan(
        floor=floor,
        buildable_zone=Rect2D(x=zone_x, y=zone_y, width=zone_w, depth=zone_d),
        rooms=rooms,
    )
    return fp


# ---------------------------------------------------------------------------
# _wall_supports_room
# ---------------------------------------------------------------------------


def test_wall_supports_room_hit():
    """Wall midpoint inside room bounds → True."""
    room = _make_room(3.0, 3.0, 4.0, 4.0)
    wall = _make_wall(3.0, 5.0, 7.0, 5.0)  # horizontal through middle of room
    assert _wall_supports_room(wall, room) is True


def test_wall_supports_room_miss():
    """Wall midpoint outside room bounds → False."""
    room = _make_room(3.0, 3.0, 4.0, 4.0)
    wall = _make_wall(0.0, 0.0, 2.0, 0.0)  # far from room
    assert _wall_supports_room(wall, room) is False


def test_wall_supports_room_edge():
    """Wall midpoint on room boundary (within tolerance) → True."""
    room = _make_room(3.0, 3.0, 4.0, 4.0)
    # Wall midpoint exactly at room's left edge (x=3.0)
    wall = _make_wall(3.0, 3.0, 3.0, 7.0)  # vertical wall at x=3.0
    assert _wall_supports_room(wall, room) is True


def test_wall_supports_room_outside_no_tol():
    """Wall midpoint well outside room → False."""
    room = _make_room(3.0, 3.0, 4.0, 4.0)
    wall = _make_wall(10.0, 10.0, 12.0, 10.0)
    assert _wall_supports_room(wall, room) is False


# ---------------------------------------------------------------------------
# build_walls_cross_floor
# ---------------------------------------------------------------------------


def test_cross_floor_marks_wall_load_bearing():
    """
    A partition wall (not load-bearing) on floor 1 should be marked
    load-bearing if an upper-floor room sits above it.
    """
    # Floor 1: one room generates walls
    floor1_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=1)]
    fp1 = _make_floor(floor1_rooms, floor=1)
    build_walls(fp1)

    # Initially all shared/external walls may already be load-bearing.
    # Manually add a partition wall that is NOT load-bearing.
    partition = WallSegment(
        start=Point2D(x=4.0, y=4.0),
        end=Point2D(x=6.0, y=4.0),
        thickness=0.12,
        is_load_bearing=False,
    )
    fp1.wall_segments.append(partition)

    # Floor 2: a room directly above the partition wall
    floor2_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=2)]
    fp2 = _make_floor(floor2_rooms, floor=2)

    build_walls_cross_floor(fp1, fp2)

    # Find our partition wall (it's the last one we appended)
    updated_partition = fp1.wall_segments[-1]
    assert updated_partition.is_load_bearing is True


def test_cross_floor_sets_structural_span():
    """Cross-floor detection should set structural_span_m on the wall."""
    floor1_rooms = [_make_room(3.0, 3.0, 6.0, 5.0, floor=1)]
    fp1 = _make_floor(floor1_rooms, floor=1)

    # Add a partition wall (3m long, horizontal)
    partition = WallSegment(
        start=Point2D(x=3.0, y=5.5),
        end=Point2D(x=6.0, y=5.5),
        thickness=0.12,
        is_load_bearing=False,
    )
    fp1.wall_segments = [partition]

    # Upper floor room directly above
    floor2_rooms = [_make_room(3.0, 3.0, 6.0, 5.0, floor=2)]
    fp2 = _make_floor(floor2_rooms, floor=2)

    build_walls_cross_floor(fp1, fp2)

    wall = fp1.wall_segments[0]
    assert wall.is_load_bearing is True
    assert wall.structural_span_m == pytest.approx(3.0, abs=0.05)


def test_cross_floor_no_upper_floor_no_change():
    """With upper_floor_plan=None, wall states should not change."""
    floor1_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=1)]
    fp1 = _make_floor(floor1_rooms, floor=1)
    partition = WallSegment(
        start=Point2D(x=3.0, y=5.0),
        end=Point2D(x=7.0, y=5.0),
        thickness=0.12,
        is_load_bearing=False,
    )
    fp1.wall_segments = [partition]

    build_walls_cross_floor(fp1, None)

    assert fp1.wall_segments[0].is_load_bearing is False


def test_cross_floor_skips_already_load_bearing():
    """
    A wall already marked is_load_bearing=True should not be re-processed
    (structural_span_m remains None if set before cross-floor detection).
    """
    floor1_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=1)]
    fp1 = _make_floor(floor1_rooms, floor=1)
    already_lb = WallSegment(
        start=Point2D(x=3.0, y=5.0),
        end=Point2D(x=7.0, y=5.0),
        thickness=0.23,
        is_load_bearing=True,
        structural_span_m=None,
    )
    fp1.wall_segments = [already_lb]

    floor2_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=2)]
    fp2 = _make_floor(floor2_rooms, floor=2)

    build_walls_cross_floor(fp1, fp2)

    # structural_span_m stays None (was already load-bearing, skipped)
    assert fp1.wall_segments[0].structural_span_m is None


def test_cross_floor_wall_not_under_upper_room():
    """Wall whose midpoint is outside upper-floor rooms stays non-load-bearing."""
    floor1_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=1)]
    fp1 = _make_floor(floor1_rooms, floor=1)
    partition = WallSegment(
        start=Point2D(x=10.0, y=10.0),
        end=Point2D(x=14.0, y=10.0),
        thickness=0.12,
        is_load_bearing=False,
    )
    fp1.wall_segments = [partition]

    # Upper floor room is far away from partition
    floor2_rooms = [_make_room(3.0, 3.0, 4.0, 4.0, floor=2)]
    fp2 = _make_floor(floor2_rooms, floor=2)

    build_walls_cross_floor(fp1, fp2)

    assert fp1.wall_segments[0].is_load_bearing is False
