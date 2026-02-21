"""
Wall builder.

Derives WallSegment objects from a FloorPlan's room layouts.

Algorithm
---------
1. For every room, emit 4 wall segments (N, S, E, W edges of bounds).
2. Tag each segment as external if it lies on the buildable-zone boundary.
3. Deduplicate shared walls: when two rooms share an edge, emit ONE segment
   with is_load_bearing=True.
4. Return the deduplicated list attached to the FloorPlan.

Coordinate system: same as RoomLayout.bounds — plot coordinates (metres).

Usage
-----
    from civilengineer.geometry_engine.wall_builder import build_walls
    floor_plan.wall_segments = build_walls(floor_plan)
"""

from __future__ import annotations

from civilengineer.schemas.design import FloorPlan, Point2D, Rect2D, WallSegment

# Snapping tolerance (metres) — segments within this distance are considered identical
_TOL = 0.02

# Wall thickness (metres)
_WALL_THICKNESS_EXT  = 0.35   # external: 350 mm (brick + insulation + plaster)
_WALL_THICKNESS_INT  = 0.23   # internal: 230 mm (9" brick or block)
_WALL_THICKNESS_PART = 0.12   # partition: 120 mm (4.5" brick)


def build_walls(floor_plan: FloorPlan) -> list[WallSegment]:
    """
    Build and deduplicate wall segments from all rooms on a floor.

    Returns a list of WallSegment; also mutates floor_plan.wall_segments in-place.
    """
    zone = floor_plan.buildable_zone
    raw_segments: list[_RawSegment] = []

    for room in floor_plan.rooms:
        b = room.bounds
        # South wall
        raw_segments.append(_RawSegment(
            x1=b.x, y1=b.y, x2=b.x + b.width, y2=b.y,
            is_external=room.is_external_wall_south,
        ))
        # North wall
        raw_segments.append(_RawSegment(
            x1=b.x, y1=b.y + b.depth, x2=b.x + b.width, y2=b.y + b.depth,
            is_external=room.is_external_wall_north,
        ))
        # West wall
        raw_segments.append(_RawSegment(
            x1=b.x, y1=b.y, x2=b.x, y2=b.y + b.depth,
            is_external=room.is_external_wall_west,
        ))
        # East wall
        raw_segments.append(_RawSegment(
            x1=b.x + b.width, y1=b.y, x2=b.x + b.width, y2=b.y + b.depth,
            is_external=room.is_external_wall_east,
        ))

    # Deduplicate: count how many rooms share each segment
    dedup = _deduplicate(raw_segments)

    result: list[WallSegment] = []
    for seg, count in dedup.items():
        is_ext = seg.is_external or _touches_zone_boundary(seg, zone)
        is_shared = count > 1  # shared between two rooms → load bearing
        thickness = (
            _WALL_THICKNESS_EXT  if is_ext
            else _WALL_THICKNESS_INT if is_shared
            else _WALL_THICKNESS_PART
        )
        result.append(WallSegment(
            start=Point2D(x=seg.x1, y=seg.y1),
            end=Point2D(x=seg.x2, y=seg.y2),
            thickness=thickness,
            is_load_bearing=is_shared or is_ext,
            is_external=is_ext,
        ))

    floor_plan.wall_segments = result
    return result


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


class _RawSegment:
    """Canonical line segment (normalised so x1≤x2, then y1≤y2)."""

    __slots__ = ("x1", "y1", "x2", "y2", "is_external")

    def __init__(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        is_external: bool,
    ) -> None:
        # Normalise: smaller coordinate first
        if (x1, y1) > (x2, y2):
            x1, y1, x2, y2 = x2, y2, x1, y1
        self.x1 = round(x1, 3)
        self.y1 = round(y1, 3)
        self.x2 = round(x2, 3)
        self.y2 = round(y2, 3)
        self.is_external = is_external

    def key(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def __hash__(self) -> int:
        return hash(self.key())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _RawSegment):
            return NotImplemented
        return (
            abs(self.x1 - other.x1) < _TOL
            and abs(self.y1 - other.y1) < _TOL
            and abs(self.x2 - other.x2) < _TOL
            and abs(self.y2 - other.y2) < _TOL
        )


def _deduplicate(segments: list[_RawSegment]) -> dict[_RawSegment, int]:
    """
    Return a dict mapping each unique segment to how many rooms share it.
    If a segment appears twice it is a shared (internal) wall.
    is_external=True on ANY occurrence propagates to the merged entry.
    """
    seen: dict[tuple[float, float, float, float], _RawSegment] = {}
    counts: dict[tuple[float, float, float, float], int] = {}

    for seg in segments:
        k = _snap_key(seg)
        if k not in seen:
            seen[k] = seg
            counts[k] = 1
        else:
            counts[k] += 1
            if seg.is_external:
                seen[k].is_external = True

    return {seen[k]: counts[k] for k in seen}


def _snap_key(seg: _RawSegment) -> tuple[float, float, float, float]:
    """Round coordinates to nearest _TOL for dict lookup."""
    inv = 1.0 / _TOL
    return (
        round(seg.x1 * inv) / inv,
        round(seg.y1 * inv) / inv,
        round(seg.x2 * inv) / inv,
        round(seg.y2 * inv) / inv,
    )


def _touches_zone_boundary(seg: _RawSegment, zone: Rect2D) -> bool:
    """Return True if the segment lies on any edge of the buildable zone."""
    tol = _TOL
    zx1, zy1 = zone.x, zone.y
    zx2, zy2 = zone.x + zone.width, zone.y + zone.depth

    # South edge: y == zone.y
    if abs(seg.y1 - zy1) < tol and abs(seg.y2 - zy1) < tol:
        return True
    # North edge: y == zone.y + zone.depth
    if abs(seg.y1 - zy2) < tol and abs(seg.y2 - zy2) < tol:
        return True
    # West edge: x == zone.x
    if abs(seg.x1 - zx1) < tol and abs(seg.x2 - zx1) < tol:
        return True
    # East edge: x == zone.x + zone.width
    if abs(seg.x1 - zx2) < tol and abs(seg.x2 - zx2) < tol:
        return True
    return False
