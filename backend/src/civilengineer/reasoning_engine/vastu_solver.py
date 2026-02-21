"""
Vastu Shastra placement scorer and optimizer.

After CP-SAT produces a room layout, this module:
  1. Scores each room for Vastu compliance (0.0–1.0 per room)
  2. Produces a `VastuScore` summary
  3. Optionally swaps room positions to improve Vastu compliance
     (swap = exchange x,y positions of two placed rooms of compatible size)

Vastu zones on a rectangular plot (facing south — most common):
  ┌──────NW──────┬──────NE──────┐
  │   Bathroom   │  Pooja Room  │ ← North half
  ├──────SW──────┼──────SE──────┤
  │ Master Bed   │   Kitchen    │ ← South half
  └──────────────┴──────────────┘
  West half          East half

For north-facing plots, rotate 90° clockwise; east-facing = 180°; etc.
We normalise the plot to south-facing convention by applying the rotation.

Only active when `requirements.vastu_compliant == True`.

Usage
-----
    from civilengineer.reasoning_engine.vastu_solver import score_vastu, optimize_vastu

    vastu = score_vastu(placed_rooms, buildable_zone, plot_facing="south")
    print(vastu.overall_score)           # 0.0 – 1.0
    print(vastu.violations)              # list of room types in wrong zone

    improved = optimize_vastu(placed_rooms, buildable_zone, plot_facing="south")
    # improved has the same rooms but some x,y positions swapped
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from civilengineer.reasoning_engine.constraint_solver import PlacedRoom
from civilengineer.schemas.design import Rect2D, RoomType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vastu zone preferred room types
# (quadrant → preferred room types, in priority order)
# ---------------------------------------------------------------------------

_PREFERRED_ZONES: dict[str, list[RoomType]] = {
    "SE": [RoomType.KITCHEN],
    "SW": [RoomType.MASTER_BEDROOM],
    "NE": [RoomType.POOJA_ROOM],
    "NW": [RoomType.BATHROOM, RoomType.TOILET],
    "N":  [RoomType.LIVING_ROOM],    # North — guest reception
    "S":  [RoomType.GARAGE, RoomType.STORE],  # South — service
    "E":  [RoomType.DINING_ROOM, RoomType.HOME_OFFICE],
    "W":  [RoomType.BEDROOM],
}

# Room types that Vastu cares about (others are free)
_VASTU_CONSTRAINED: frozenset[RoomType] = frozenset(
    {
        RoomType.KITCHEN,
        RoomType.MASTER_BEDROOM,
        RoomType.POOJA_ROOM,
        RoomType.BATHROOM,
        RoomType.TOILET,
    }
)

# Facing → rotation angle in degrees (maps plot orientation to south-facing convention)
_FACING_ROTATION: dict[str, float] = {
    "south":     0.0,
    "north":   180.0,
    "east":     90.0,
    "west":    270.0,
    "southeast": 45.0,
    "southwest":315.0,
    "northeast": 135.0,
    "northwest": 225.0,
}


# ---------------------------------------------------------------------------
# Zone classifier
# ---------------------------------------------------------------------------


def _classify_zone(
    cx: float, cy: float,
    zone_w: float, zone_d: float,
    facing: str = "south",
) -> str:
    """
    Classify centroid (cx, cy) within buildable zone (w × d) into a Vastu quadrant.

    Returns one of: NE, NW, SE, SW, N, S, E, W.
    """
    # Normalise to [0,1] × [0,1]
    nx = cx / zone_w if zone_w > 0 else 0.5
    ny = cy / zone_d if zone_d > 0 else 0.5

    # Apply facing rotation: rotate the quadrant interpretation
    # (simplification — we only support cardinal facings here)
    rotation = _FACING_ROTATION.get(facing.lower(), 0.0)
    if rotation == 180.0:
        nx, ny = 1.0 - nx, 1.0 - ny
    elif rotation == 90.0:
        nx, ny = ny, 1.0 - nx
    elif rotation == 270.0:
        nx, ny = 1.0 - ny, nx

    # Map to quadrant
    threshold = 0.5
    is_north = ny >= threshold
    is_east  = nx >= threshold
    is_south = not is_north
    is_west  = not is_east

    if is_north and is_east:
        return "NE"
    if is_north and is_west:
        return "NW"
    if is_south and is_east:
        return "SE"
    return "SW"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class VastuRoomResult:
    room_req: RoomType
    actual_zone: str
    preferred_zone: str | None
    compliant: bool
    score: float   # 1.0 = perfect, 0.5 = neutral, 0.0 = forbidden


@dataclass
class VastuScore:
    overall_score: float                       # 0.0–1.0 weighted average
    room_results: list[VastuRoomResult] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)   # room type strings

    def __str__(self) -> str:
        return (
            f"VastuScore {self.overall_score:.2f} "
            f"({len(self.violations)} violation(s): {self.violations})"
        )


def _preferred_zone_for(room_type: RoomType) -> str | None:
    for zone, types in _PREFERRED_ZONES.items():
        if room_type in types:
            return zone
    return None


def score_vastu(
    placed_rooms: list[PlacedRoom],
    buildable_zone: Rect2D,
    facing: str = "south",
) -> VastuScore:
    """
    Score a list of PlacedRoom objects for Vastu compliance.

    Only constrained room types contribute to the score.
    Unconstrained rooms get score=1.0 automatically.
    """
    results: list[VastuRoomResult] = []
    violations: list[str] = []
    scores: list[float] = []

    for pr in placed_rooms:
        rt = pr.room_req.room_type
        if rt not in _VASTU_CONSTRAINED:
            results.append(
                VastuRoomResult(rt, "any", None, compliant=True, score=1.0)
            )
            continue

        cx = pr.x + pr.width  / 2
        cy = pr.y + pr.depth  / 2
        zone = _classify_zone(cx, cy, buildable_zone.width, buildable_zone.depth, facing)
        pref = _preferred_zone_for(rt)

        if pref is None:
            compliant = True
            score = 1.0
        elif zone == pref:
            compliant = True
            score = 1.0
        else:
            compliant = False
            score = 0.0
            violations.append(f"{rt.value} in {zone} (should be {pref})")

        scores.append(score)
        results.append(VastuRoomResult(rt, zone, pref, compliant, score))

    overall = sum(scores) / len(scores) if scores else 1.0

    return VastuScore(
        overall_score=round(overall, 3),
        room_results=results,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Optimizer — swap rooms to improve Vastu score
# ---------------------------------------------------------------------------


def optimize_vastu(
    placed_rooms: list[PlacedRoom],
    buildable_zone: Rect2D,
    facing: str = "south",
    max_swaps: int = 10,
) -> list[PlacedRoom]:
    """
    Attempt to improve Vastu compliance by swapping room positions.

    Two rooms can be swapped if their dimensions are compatible (within 20%
    tolerance in each direction). Returns a new list with improved placement.

    The original list is not modified.
    """
    import copy  # noqa: PLC0415

    rooms = [copy.copy(r) for r in placed_rooms]
    current_score = score_vastu(rooms, buildable_zone, facing)

    swaps_done = 0
    improved = True

    while improved and swaps_done < max_swaps:
        improved = False
        for i, a in enumerate(rooms):
            if a.room_req.room_type not in _VASTU_CONSTRAINED:
                continue
            pref_a = _preferred_zone_for(a.room_req.room_type)
            if pref_a is None:
                continue

            for j, b in enumerate(rooms):
                if i >= j:
                    continue
                if not _dimensions_compatible(a, b):
                    continue

                # Try swap
                rooms[i], rooms[j] = _swap_positions(rooms[i], rooms[j])
                new_score = score_vastu(rooms, buildable_zone, facing)

                if new_score.overall_score > current_score.overall_score:
                    current_score = new_score
                    swaps_done += 1
                    improved = True
                    logger.debug(
                        "Vastu swap: %s ↔ %s → score %.3f",
                        a.room_req.room_type, b.room_req.room_type,
                        new_score.overall_score,
                    )
                    break  # restart inner loop after successful swap
                else:
                    # Revert
                    rooms[i], rooms[j] = _swap_positions(rooms[i], rooms[j])

            if improved:
                break

    logger.info(
        "optimize_vastu: %d swaps, final score %.3f",
        swaps_done, current_score.overall_score,
    )
    return rooms


def _dimensions_compatible(a: PlacedRoom, b: PlacedRoom, tol: float = 0.20) -> bool:
    """
    Return True if rooms can be swapped:
    either (a_w ≈ b_w and a_d ≈ b_d) or (a_w ≈ b_d and a_d ≈ b_w).
    Tolerance is a fraction of the larger dimension.
    """
    def near(x: float, y: float) -> bool:
        return abs(x - y) <= tol * max(x, y, 0.1)

    same_orientation = near(a.width, b.width) and near(a.depth, b.depth)
    flipped         = near(a.width, b.depth) and near(a.depth, b.width)
    return same_orientation or flipped


def _swap_positions(a: PlacedRoom, b: PlacedRoom) -> tuple[PlacedRoom, PlacedRoom]:
    """Return new PlacedRoom objects with x,y swapped."""
    import copy  # noqa: PLC0415
    new_a = copy.copy(a)
    new_b = copy.copy(b)
    new_a.x, new_a.y = b.x, b.y
    new_b.x, new_b.y = a.x, a.y
    return new_a, new_b
