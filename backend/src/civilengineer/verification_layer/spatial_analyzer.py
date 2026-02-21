"""
Spatial analysis of a BuildingDesign / FloorPlan.

Provides:
  - Adjacency graph  (which rooms share a wall)
  - Overlap detection (rooms must not overlap)
  - Circulation check (all rooms reachable from the entrance)
  - Vastu zone classification (SE / SW / NE / NW quadrant)
  - External window coverage (every habitable room has an exterior window)

All inputs are plain dicts (as stored in AgentState) or typed Pydantic models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from civilengineer.schemas.design import (
    FloorPlan,
    RoomLayout,
    RoomType,
    WallFace,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Habitable room types (must have natural light + ventilation)
# ---------------------------------------------------------------------------

_HABITABLE: frozenset[RoomType] = frozenset(
    {
        RoomType.MASTER_BEDROOM,
        RoomType.BEDROOM,
        RoomType.LIVING_ROOM,
        RoomType.DINING_ROOM,
        RoomType.KITCHEN,
        RoomType.HOME_OFFICE,
    }
)

# Rooms that must be reachable from entrance for circulation
_CIRCULATION_REQUIRED: frozenset[RoomType] = frozenset(
    {
        RoomType.MASTER_BEDROOM,
        RoomType.BEDROOM,
        RoomType.LIVING_ROOM,
        RoomType.KITCHEN,
        RoomType.BATHROOM,
    }
)

_TOLERANCE = 0.05  # metres — shared-wall detection tolerance


# ---------------------------------------------------------------------------
# Adjacency graph
# ---------------------------------------------------------------------------


@dataclass
class AdjacencyEdge:
    room_a: str   # room_id
    room_b: str   # room_id
    shared_length: float  # metres of shared boundary


def build_adjacency_graph(floor_plan: FloorPlan) -> dict[str, list[AdjacencyEdge]]:
    """
    Return a dict mapping room_id → list of AdjacencyEdge.

    Two rooms are adjacent if they share a contiguous edge segment of length > 0.
    Detection: for each pair, check whether any edge of A coincides with an edge of B.
    """
    rooms = floor_plan.rooms
    graph: dict[str, list[AdjacencyEdge]] = {r.room_id: [] for r in rooms}

    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            shared = _shared_wall_length(a, b)
            if shared > _TOLERANCE:
                edge_a = AdjacencyEdge(a.room_id, b.room_id, shared)
                edge_b = AdjacencyEdge(b.room_id, a.room_id, shared)
                graph[a.room_id].append(edge_a)
                graph[b.room_id].append(edge_b)

    return graph


def _shared_wall_length(a: RoomLayout, b: RoomLayout) -> float:
    """
    Return length of shared segment between room a and b, or 0.0.

    Check all 4 edge-pairs. A shared edge exists when:
      - One edge of A is collinear with one edge of B
      - Their projections overlap
    """
    ax1, ay1 = a.bounds.x, a.bounds.y
    ax2, ay2 = ax1 + a.bounds.width, ay1 + a.bounds.depth
    bx1, by1 = b.bounds.x, b.bounds.y
    bx2, by2 = bx1 + b.bounds.width, by1 + b.bounds.depth

    best = 0.0

    # Horizontal edges of A vs horizontal edges of B
    for ay in (ay1, ay2):
        for by in (by1, by2):
            if abs(ay - by) < _TOLERANCE:
                # Overlapping projection on x-axis
                overlap = min(ax2, bx2) - max(ax1, bx1)
                if overlap > 0:
                    best = max(best, overlap)

    # Vertical edges of A vs vertical edges of B
    for ax in (ax1, ax2):
        for bx in (bx1, bx2):
            if abs(ax - bx) < _TOLERANCE:
                overlap = min(ay2, by2) - max(ay1, by1)
                if overlap > 0:
                    best = max(best, overlap)

    return best


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------


@dataclass
class OverlapViolation:
    room_a: str
    room_b: str
    overlap_area: float  # sqm


def find_overlaps(floor_plan: FloorPlan) -> list[OverlapViolation]:
    """Return all room pairs that geometrically overlap."""
    rooms = floor_plan.rooms
    violations: list[OverlapViolation] = []

    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            area = _overlap_area(a, b)
            if area > 0.01:  # 100 cm² threshold
                violations.append(OverlapViolation(a.room_id, b.room_id, area))

    return violations


def _overlap_area(a: RoomLayout, b: RoomLayout) -> float:
    ax1, ay1 = a.bounds.x, a.bounds.y
    ax2, ay2 = ax1 + a.bounds.width, ay1 + a.bounds.depth
    bx1, by1 = b.bounds.x, b.bounds.y
    bx2, by2 = bx1 + b.bounds.width, by1 + b.bounds.depth

    ox = min(ax2, bx2) - max(ax1, bx1)
    oy = min(ay2, by2) - max(ay1, by1)
    if ox <= 0 or oy <= 0:
        return 0.0
    return ox * oy


# ---------------------------------------------------------------------------
# Circulation check
# ---------------------------------------------------------------------------


@dataclass
class CirculationResult:
    reachable: set[str]         # room_ids reachable from entrance
    unreachable: list[str]      # room_ids not reachable
    has_entrance: bool


def check_circulation(
    floor_plan: FloorPlan,
    adjacency: dict[str, list[AdjacencyEdge]] | None = None,
) -> CirculationResult:
    """
    BFS from the entrance room to determine which rooms are reachable.

    Entrance = room with is_main_entrance door, or LIVING_ROOM on floor 1,
               or first room on floor 1 as fallback.
    """
    if adjacency is None:
        adjacency = build_adjacency_graph(floor_plan)

    # Find entrance room
    entrance_id: str | None = None
    for room in floor_plan.rooms:
        if any(d.is_main_entrance for d in room.doors):
            entrance_id = room.room_id
            break
    if entrance_id is None:
        # Fallback: living room on floor 1
        for room in floor_plan.rooms:
            if room.room_type == RoomType.LIVING_ROOM and room.floor == 1:
                entrance_id = room.room_id
                break
    if entrance_id is None and floor_plan.rooms:
        entrance_id = floor_plan.rooms[0].room_id

    has_entrance = entrance_id is not None
    if not has_entrance:
        return CirculationResult(reachable=set(), unreachable=[], has_entrance=False)

    # BFS
    visited: set[str] = set()
    queue = [entrance_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for edge in adjacency.get(current, []):
            if edge.room_b not in visited:
                queue.append(edge.room_b)

    required_room_ids = {
        r.room_id
        for r in floor_plan.rooms
        if r.room_type in _CIRCULATION_REQUIRED
    }
    unreachable = [rid for rid in required_room_ids if rid not in visited]

    return CirculationResult(
        reachable=visited,
        unreachable=unreachable,
        has_entrance=has_entrance,
    )


# ---------------------------------------------------------------------------
# Vastu zone classification
# ---------------------------------------------------------------------------


_VASTU_ZONES = {
    "NE": (RoomType.POOJA_ROOM,),
    "SE": (RoomType.KITCHEN,),
    "SW": (RoomType.MASTER_BEDROOM,),
    "NW": (RoomType.BATHROOM, RoomType.TOILET),
}

_VASTU_PREFERRED: dict[RoomType, str] = {
    rt: zone for zone, types in _VASTU_ZONES.items() for rt in types
}


@dataclass
class VastuViolation:
    room_id: str
    room_type: str
    actual_zone: str
    expected_zone: str


def classify_vastu_zone(room: RoomLayout, plot_width: float, plot_depth: float) -> str:
    """
    Return the cardinal quadrant ('NE', 'SE', 'SW', 'NW') for a room's centroid.

    Assumes: x increases east, y increases north.
    Origin (0, 0) = SW corner of plot.
    """
    cx = room.bounds.x + room.bounds.width / 2
    cy = room.bounds.y + room.bounds.depth / 2
    east = cx > plot_width / 2
    north = cy > plot_depth / 2
    if north and east:
        return "NE"
    if north and not east:
        return "NW"
    if not north and east:
        return "SE"
    return "SW"


def check_vastu_compliance(
    floor_plan: FloorPlan,
    plot_width: float,
    plot_depth: float,
) -> list[VastuViolation]:
    """
    Check if Vastu-sensitive rooms are in their preferred quadrant.
    Only checks floor 1 rooms (ground floor defines Vastu).
    """
    violations: list[VastuViolation] = []
    for room in floor_plan.rooms:
        if room.floor != 1:
            continue
        preferred = _VASTU_PREFERRED.get(room.room_type)
        if preferred is None:
            continue
        actual = classify_vastu_zone(room, plot_width, plot_depth)
        if actual != preferred:
            violations.append(
                VastuViolation(
                    room_id=room.room_id,
                    room_type=room.room_type.value,
                    actual_zone=actual,
                    expected_zone=preferred,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# External window check
# ---------------------------------------------------------------------------


@dataclass
class WindowViolation:
    room_id: str
    room_type: str
    message: str


def check_external_windows(floor_plan: FloorPlan) -> list[WindowViolation]:
    """
    Every habitable room must have at least one window on an external wall face.
    """
    violations: list[WindowViolation] = []
    for room in floor_plan.rooms:
        if room.room_type not in _HABITABLE:
            continue

        external_faces = {
            WallFace.NORTH if room.is_external_wall_north else None,
            WallFace.SOUTH if room.is_external_wall_south else None,
            WallFace.EAST if room.is_external_wall_east else None,
            WallFace.WEST if room.is_external_wall_west else None,
        } - {None}

        if not external_faces:
            violations.append(
                WindowViolation(
                    room_id=room.room_id,
                    room_type=room.room_type.value,
                    message="No external wall — natural light impossible",
                )
            )
            continue

        window_faces = {w.wall_face for w in room.windows}
        if not window_faces.intersection(external_faces):
            violations.append(
                WindowViolation(
                    room_id=room.room_id,
                    room_type=room.room_type.value,
                    message=f"Window not on any external face {external_faces}",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Adjacency constraint checks (kitchen ≠ toilet, etc.)
# ---------------------------------------------------------------------------


@dataclass
class AdjacencyConstraintViolation:
    room_a: str
    room_b: str
    message: str


# (type_a, type_b, must_be_adjacent) — False means must NOT be adjacent
_ADJACENCY_CONSTRAINTS: list[tuple[RoomType, RoomType, bool, str]] = [
    (
        RoomType.KITCHEN,
        RoomType.BATHROOM,
        False,
        "Kitchen must not be directly adjacent to bathroom/toilet",
    ),
    (
        RoomType.KITCHEN,
        RoomType.TOILET,
        False,
        "Kitchen must not be directly adjacent to toilet",
    ),
    (
        RoomType.LIVING_ROOM,
        RoomType.DINING_ROOM,
        True,
        "Living room should be adjacent to dining room",
    ),
]


def check_adjacency_constraints(
    floor_plan: FloorPlan,
    adjacency: dict[str, list[AdjacencyEdge]] | None = None,
) -> list[AdjacencyConstraintViolation]:
    """Check named adjacency rules (kitchen ≠ toilet, living ↔ dining, etc.)."""
    if adjacency is None:
        adjacency = build_adjacency_graph(floor_plan)

    type_map: dict[RoomType, list[str]] = {}
    for room in floor_plan.rooms:
        type_map.setdefault(room.room_type, []).append(room.room_id)

    violations: list[AdjacencyConstraintViolation] = []

    for type_a, type_b, must_adjacent, msg in _ADJACENCY_CONSTRAINTS:
        rooms_a = type_map.get(type_a, [])
        rooms_b = type_map.get(type_b, [])
        if not rooms_a or not rooms_b:
            continue

        # Check if any room of type_a is adjacent to any room of type_b
        is_adjacent = any(
            any(edge.room_b == b for edge in adjacency.get(a, []))
            for a in rooms_a
            for b in rooms_b
        )

        if must_adjacent and not is_adjacent:
            violations.append(
                AdjacencyConstraintViolation(rooms_a[0], rooms_b[0], msg)
            )
        elif not must_adjacent and is_adjacent:
            # Find the actual pair
            for a in rooms_a:
                for edge in adjacency.get(a, []):
                    if edge.room_b in rooms_b:
                        violations.append(
                            AdjacencyConstraintViolation(a, edge.room_b, msg)
                        )

    return violations


# ---------------------------------------------------------------------------
# Composite spatial report
# ---------------------------------------------------------------------------


@dataclass
class SpatialReport:
    floor: int
    overlaps: list[OverlapViolation] = field(default_factory=list)
    circulation: CirculationResult | None = None
    vastu_violations: list[VastuViolation] = field(default_factory=list)
    window_violations: list[WindowViolation] = field(default_factory=list)
    adjacency_violations: list[AdjacencyConstraintViolation] = field(
        default_factory=list
    )

    @property
    def has_hard_violations(self) -> bool:
        return bool(
            self.overlaps
            or (self.circulation and self.circulation.unreachable)
            or self.window_violations
        )

    @property
    def summary(self) -> str:
        parts = []
        if self.overlaps:
            parts.append(f"{len(self.overlaps)} overlap(s)")
        if self.circulation and self.circulation.unreachable:
            parts.append(f"{len(self.circulation.unreachable)} unreachable room(s)")
        if self.window_violations:
            parts.append(f"{len(self.window_violations)} window violation(s)")
        if self.vastu_violations:
            parts.append(f"{len(self.vastu_violations)} Vastu violation(s)")
        if self.adjacency_violations:
            parts.append(f"{len(self.adjacency_violations)} adjacency issue(s)")
        return "; ".join(parts) if parts else "No spatial violations"


def analyze_floor(
    floor_plan: FloorPlan,
    plot_width: float,
    plot_depth: float,
    check_vastu: bool = False,
) -> SpatialReport:
    """Run all spatial checks on a single floor plan."""
    adjacency = build_adjacency_graph(floor_plan)

    overlaps = find_overlaps(floor_plan)
    circulation = check_circulation(floor_plan, adjacency)
    window_violations = check_external_windows(floor_plan)
    adjacency_violations = check_adjacency_constraints(floor_plan, adjacency)
    vastu_violations = (
        check_vastu_compliance(floor_plan, plot_width, plot_depth)
        if check_vastu
        else []
    )

    return SpatialReport(
        floor=floor_plan.floor,
        overlaps=overlaps,
        circulation=circulation,
        vastu_violations=vastu_violations,
        window_violations=window_violations,
        adjacency_violations=adjacency_violations,
    )
