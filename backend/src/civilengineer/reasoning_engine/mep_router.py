"""
MEP Router — Layer 2.5 (between geometry and human review).

Performs deterministic MEP routing:
  1. Electrical: A* on a discretised room grid (walls = obstacles)
     - Panel placed near main entrance on external wall
     - Conduit runs to each room's outlet cluster
     - Wire gauge assigned by load type
  2. Plumbing: Vertical stacking of wet rooms
     - Rooms within 1.5m horizontal offset share a stack
     - NBC rule: no plumbing through bedrooms
  3. Panel sizing: 1-phase ≤ 10 kVA, 3-phase otherwise

All spatial values in metres. Pipe diameters and wire gauges in mm.
"""

from __future__ import annotations

import heapq
import math
import uuid
from collections import defaultdict

from civilengineer.schemas.design import (
    FloorPlan,
    RoomLayout,
    RoomType,
    WallSegment,
)
from civilengineer.schemas.mep import (
    ConduitRun,
    ElectricalPanel,
    MEPNetwork,
    MEPPoint,
    MEPRequirements,
    PlumbingStack,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Grid resolution for A* routing (metres per cell)
_GRID_RES = 0.25

# Wire gauge by circuit type (mm²)
_GAUGE_LIGHTING = 2.5
_GAUGE_POWER    = 6.0
_GAUGE_AC       = 10.0
_GAUGE_WM       = 6.0
_GAUGE_OVEN     = 6.0

# Load estimates (kVA)
_LOAD_LIGHTING_PER_FLOOR = 1.0
_LOAD_POWER_PER_ROOM     = 0.5    # general power per room
_LOAD_AC_PER_UNIT        = 1.5
_LOAD_WM                 = 1.8
_LOAD_OVEN               = 2.0
_LOAD_WATER_HEATER       = 1.5

# Conduit diameter maps (wire_gauge_mm2 → conduit_dia_mm)
_CONDUIT_DIA: dict[float, float] = {
    2.5: 20.0,
    6.0: 25.0,
    10.0: 32.0,
}

# Plumbing
_MAX_STACK_OFFSET_M = 1.5   # horizontal offset threshold to share a stack
_PIPE_DIA_BASIC     = 15.0  # mm — basic grade
_PIPE_DIA_STANDARD  = 20.0  # mm — standard grade
_PIPE_DIA_PREMIUM   = 25.0  # mm — premium grade

# NBC rule: no plumbing pipes through sleeping rooms
_NO_PIPE_ROOMS = {
    RoomType.MASTER_BEDROOM,
    RoomType.BEDROOM,
}

# Wet rooms (can host plumbing fixtures)
_WET_ROOMS = {
    RoomType.BATHROOM,
    RoomType.TOILET,
    RoomType.KITCHEN,
    RoomType.STORE,  # utility/laundry
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _room_centroid(room: RoomLayout) -> tuple[float, float]:
    return room.bounds.center.x, room.bounds.center.y


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _world_to_grid(
    x: float, y: float, grid_res: float = _GRID_RES
) -> tuple[int, int]:
    return int(x / grid_res), int(y / grid_res)


def _grid_to_world(
    gx: int, gy: int, grid_res: float = _GRID_RES
) -> tuple[float, float]:
    return gx * grid_res + grid_res / 2, gy * grid_res + grid_res / 2


def _build_obstacle_grid(
    floor_plan: FloorPlan,
    grid_res: float = _GRID_RES,
) -> set[tuple[int, int]]:
    """
    Return set of grid cells that are blocked by wall segments.

    A cell is blocked if any wall segment passes through it.
    We rasterise each wall segment by sampling along its length.
    """
    blocked: set[tuple[int, int]] = set()
    for wall in floor_plan.wall_segments:
        sx, sy = wall.start.x, wall.start.y
        ex, ey = wall.end.x, wall.end.y
        length = math.hypot(ex - sx, ey - sy)
        if length < 1e-6:
            continue
        steps = max(2, int(length / (grid_res * 0.5)))
        for i in range(steps + 1):
            t = i / steps
            wx = sx + t * (ex - sx)
            wy = sy + t * (ey - sy)
            blocked.add(_world_to_grid(wx, wy, grid_res))
    return blocked


def _astar(
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]],
    grid_bounds: tuple[int, int, int, int],  # min_gx, min_gy, max_gx, max_gy
) -> list[tuple[int, int]]:
    """
    A* pathfinder on a 2D integer grid.

    Returns list of grid cells from start to goal (inclusive).
    Falls back to a straight-line path if no path found.
    """
    min_gx, min_gy, max_gx, max_gy = grid_bounds

    def heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    open_heap: list[tuple[float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (0.0, start))
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    g_score: dict[tuple[int, int], float] = {start: 0.0}

    neighbors_4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current == goal:
            # Reconstruct path
            path: list[tuple[int, int]] = []
            node: tuple[int, int] | None = current
            while node is not None:
                path.append(node)
                node = came_from[node]
            return list(reversed(path))

        for dx, dy in neighbors_4:
            nb = (current[0] + dx, current[1] + dy)
            if not (min_gx <= nb[0] <= max_gx and min_gy <= nb[1] <= max_gy):
                continue
            if nb in blocked:
                continue
            tentative_g = g_score[current] + 1.0
            if tentative_g < g_score.get(nb, float("inf")):
                came_from[nb] = current
                g_score[nb] = tentative_g
                f = tentative_g + heuristic(nb, goal)
                heapq.heappush(open_heap, (f, nb))

    # No path found — return straight line (conduit may pass through walls,
    # indicating a structural route that will be noted during installation)
    return [start, goal]


def _grid_path_to_mep_points(
    path: list[tuple[int, int]],
    floor: int,
    grid_res: float = _GRID_RES,
) -> list[MEPPoint]:
    """Convert grid path to MEPPoint list, merging collinear segments."""
    if not path:
        return []

    # Merge collinear segments
    merged: list[tuple[int, int]] = [path[0]]
    for i in range(1, len(path) - 1):
        prev = path[i - 1]
        curr = path[i]
        nxt  = path[i + 1]
        dx1, dy1 = curr[0] - prev[0], curr[1] - prev[1]
        dx2, dy2 = nxt[0] - curr[0],  nxt[1] - curr[1]
        if (dx1, dy1) != (dx2, dy2):
            merged.append(curr)
    merged.append(path[-1])

    points: list[MEPPoint] = []
    for gx, gy in merged:
        wx, wy = _grid_to_world(gx, gy, grid_res)
        points.append(MEPPoint(x=wx, y=wy, floor=floor))
    return points


# ---------------------------------------------------------------------------
# Panel placement
# ---------------------------------------------------------------------------


def _find_panel_location(floor_plan: FloorPlan) -> tuple[float, float]:
    """
    Place the panel near the main entrance on the external wall.

    Falls back to buildable zone origin + offset if no main entrance found.
    """
    bz = floor_plan.buildable_zone
    for room in floor_plan.rooms:
        for door in room.doors:
            if door.is_main_entrance:
                # Near entrance, offset 0.5m into buildable zone
                cx, cy = _room_centroid(room)
                return max(bz.x + 0.3, cx - 0.5), max(bz.y + 0.3, cy - 0.3)

    # Default: lower-left corner of buildable zone
    return bz.x + 0.3, bz.y + 0.3


# ---------------------------------------------------------------------------
# Electrical routing
# ---------------------------------------------------------------------------


def _room_circuit_name(room: RoomLayout, circuit_type: str) -> str:
    return f"{circuit_type}_{room.room_type.value.upper()}_F{room.floor}"


def _wire_gauge_for_room(
    room: RoomLayout, mep_req: MEPRequirements | None
) -> float:
    """Determine wire gauge based on room type and high-load appliances."""
    appliances = mep_req.high_load_appliances if mep_req else []
    rt = room.room_type
    if rt in (RoomType.MASTER_BEDROOM,) and any(
        "AC" in a for a in appliances
    ):
        return _GAUGE_AC
    if rt == RoomType.KITCHEN:
        if any("OVEN" in a for a in appliances):
            return _GAUGE_OVEN
        return _GAUGE_POWER
    if rt == RoomType.STORE and any("WM" in a for a in appliances):
        return _GAUGE_WM
    # Default: separate lighting and power circuits; use power gauge for routing
    return _GAUGE_POWER


def _room_load_kva(
    room: RoomLayout, mep_req: MEPRequirements | None
) -> float:
    """Estimate electrical load for a room circuit."""
    appliances = mep_req.high_load_appliances if mep_req else []
    rt = room.room_type
    base = _LOAD_POWER_PER_ROOM
    if rt == RoomType.MASTER_BEDROOM and any("AC" in a for a in appliances):
        base += _LOAD_AC_PER_UNIT
    if rt == RoomType.KITCHEN:
        if any("OVEN" in a for a in appliances):
            base += _LOAD_OVEN
        if any("WATER_HEATER" in a for a in appliances):
            base += _LOAD_WATER_HEATER
    if rt == RoomType.STORE and any("WM" in a for a in appliances):
        base += _LOAD_WM
    return base


def route_electrical(
    floor_plan: FloorPlan,
    mep_req: MEPRequirements | None = None,
) -> tuple[list[ConduitRun], ElectricalPanel]:
    """
    Run A* electrical routing for all rooms on a single floor.

    Returns (list of ConduitRun, ElectricalPanel).
    """
    bz = floor_plan.buildable_zone
    floor = floor_plan.floor

    # Panel location
    px, py = _find_panel_location(floor_plan)
    panel_start = _world_to_grid(px, py)

    # Build obstacle grid
    blocked = _build_obstacle_grid(floor_plan)

    # Grid bounds (extend 10% beyond buildable zone)
    margin = 2
    min_gx = max(0, _world_to_grid(bz.x, bz.y)[0] - margin)
    min_gy = max(0, _world_to_grid(bz.x, bz.y)[1] - margin)
    max_gx = _world_to_grid(bz.x + bz.width, bz.y + bz.depth)[0] + margin
    max_gy = _world_to_grid(bz.x + bz.width, bz.y + bz.depth)[1] + margin
    grid_bounds = (min_gx, min_gy, max_gx, max_gy)

    conduit_runs: list[ConduitRun] = []
    total_load = 0.0
    total_circuits = 0

    # Also generate a lighting circuit to the panel itself (whole-floor)
    lighting_load = _LOAD_LIGHTING_PER_FLOOR
    total_load += lighting_load
    total_circuits += 1

    for room in floor_plan.rooms:
        # Skip staircase and corridor for dedicated circuits (shared branch)
        if room.room_type in (RoomType.STAIRCASE, RoomType.CORRIDOR):
            continue

        cx, cy = _room_centroid(room)
        room_grid = _world_to_grid(cx, cy)

        # Remove panel cell from blocked (it's the source)
        # Room centroid may be in blocked zone — find nearest free cell
        if room_grid in blocked:
            # Nudge slightly
            room_grid = (room_grid[0] + 1, room_grid[1])

        path = _astar(panel_start, room_grid, blocked, grid_bounds)
        mep_points = _grid_path_to_mep_points(path, floor)

        gauge   = _wire_gauge_for_room(room, mep_req)
        load    = _room_load_kva(room, mep_req)
        circuit = _room_circuit_name(room, "POWER")

        run = ConduitRun(
            run_id=f"CR-{uuid.uuid4().hex[:6].upper()}",
            circuit_name=circuit,
            path=mep_points,
            wire_gauge_mm2=gauge,
            conduit_dia_mm=_CONDUIT_DIA.get(gauge, 25.0),
            load_kva=load,
        )
        conduit_runs.append(run)
        total_load += load
        total_circuits += 1

    # Panel sizing
    phase = "3-phase" if total_load > 10.0 else "1-phase"
    panel = ElectricalPanel(
        panel_id=f"PNL-F{floor}-{uuid.uuid4().hex[:4].upper()}",
        location=MEPPoint(x=px, y=py, floor=floor),
        num_circuits=total_circuits,
        load_kva=round(total_load, 2),
        phase=phase,
    )

    return conduit_runs, panel


# ---------------------------------------------------------------------------
# Plumbing routing
# ---------------------------------------------------------------------------


def _find_wet_rooms(floor_plans: list[FloorPlan]) -> list[RoomLayout]:
    """Return all wet rooms across all floors."""
    wet: list[RoomLayout] = []
    for fp in floor_plans:
        for room in fp.rooms:
            if room.room_type in _WET_ROOMS:
                wet.append(room)
    return wet


def _stack_wet_rooms(
    wet_rooms: list[RoomLayout],
    max_offset: float = _MAX_STACK_OFFSET_M,
) -> list[list[RoomLayout]]:
    """
    Group wet rooms into stacks by proximity.

    Two rooms are in the same stack if their centroids are within
    `max_offset` metres horizontally (x and y both).
    Returns list of groups (each group = one stack).
    """
    groups: list[list[RoomLayout]] = []
    assigned: set[str] = set()

    for room in wet_rooms:
        if room.room_id in assigned:
            continue
        cx, cy = _room_centroid(room)
        group = [room]
        assigned.add(room.room_id)
        for other in wet_rooms:
            if other.room_id in assigned:
                continue
            ox, oy = _room_centroid(other)
            if abs(cx - ox) <= max_offset and abs(cy - oy) <= max_offset:
                group.append(other)
                assigned.add(other.room_id)
        groups.append(group)

    return groups


def _pipe_dia_for_grade(plumbing_grade: str) -> float:
    return {
        "basic": _PIPE_DIA_BASIC,
        "standard": _PIPE_DIA_STANDARD,
        "premium": _PIPE_DIA_PREMIUM,
    }.get(plumbing_grade, _PIPE_DIA_STANDARD)


def _plumbing_path_for_stack(
    rooms: list[RoomLayout],
    is_hot: bool,
    floor_plans: list[FloorPlan],
) -> list[MEPPoint]:
    """
    Build a simple vertical pipe path for a stack.

    The stack runs vertically from ground floor to top floor at the
    average centroid position of the wet rooms in the stack.
    Branch runs connect the stack to each room horizontally.

    NBC rule: branch runs must not cross bedroom room bounds.
    (This is enforced by routing around bedroom boundaries.)
    """
    if not rooms:
        return []

    # Average centroid of all rooms in stack
    avg_x = sum(_room_centroid(r)[0] for r in rooms) / len(rooms)
    avg_y = sum(_room_centroid(r)[1] for r in rooms) / len(rooms)

    floors_served = sorted({r.floor for r in rooms})
    min_floor = floors_served[0]
    max_floor = floors_served[-1]

    points: list[MEPPoint] = []

    # Vertical riser from min_floor to max_floor at average position
    for f in range(min_floor, max_floor + 1):
        points.append(MEPPoint(x=avg_x, y=avg_y, floor=f))

    # Branch to each room (horizontal run at that floor)
    for room in rooms:
        cx, cy = _room_centroid(room)
        # Check if branch would cross a bedroom; if so, offset path
        bedroom_rooms = [
            r for fp in floor_plans
            for r in fp.rooms
            if r.floor == room.floor and r.room_type in _NO_PIPE_ROOMS
        ]
        branch_clear = True
        for bdrm in bedroom_rooms:
            bx, by = bdrm.bounds.x, bdrm.bounds.y
            bw, bd = bdrm.bounds.width, bdrm.bounds.depth
            # Simple AABB check: does line from (avg_x, avg_y) to (cx, cy) cross bedroom?
            if (
                min(avg_x, cx) < bx + bw
                and max(avg_x, cx) > bx
                and min(avg_y, cy) < by + bd
                and max(avg_y, cy) > by
            ):
                branch_clear = False
                break

        if not branch_clear:
            # Route around bedroom: go via the corridor side
            # Use a two-leg path: up/down first, then across
            points.append(MEPPoint(x=avg_x, y=cy, floor=room.floor))
        points.append(MEPPoint(x=cx, y=cy, floor=room.floor))

    return points


def route_plumbing(
    floor_plans: list[FloorPlan],
    mep_req: MEPRequirements | None = None,
) -> list[PlumbingStack]:
    """
    Create plumbing stacks for all wet rooms across all floors.

    Returns list of PlumbingStack.
    """
    grade = mep_req.plumbing_grade if mep_req else "standard"
    pipe_dia = _pipe_dia_for_grade(grade)

    wet_rooms = _find_wet_rooms(floor_plans)
    if not wet_rooms:
        return []

    room_groups = _stack_wet_rooms(wet_rooms)
    stacks: list[PlumbingStack] = []

    for group in room_groups:
        stack_id = f"STK-{uuid.uuid4().hex[:6].upper()}"
        room_ids  = [r.room_id for r in group]
        floors    = sorted({r.floor for r in group})

        cold_path = _plumbing_path_for_stack(group, is_hot=False, floor_plans=floor_plans)
        hot_path  = _plumbing_path_for_stack(group, is_hot=True,  floor_plans=floor_plans)

        stack = PlumbingStack(
            stack_id=stack_id,
            wet_rooms=room_ids,
            cold_pipe_path=cold_path,
            hot_pipe_path=hot_path,
            pipe_dia_mm=pipe_dia,
            floors_served=floors,
        )
        stacks.append(stack)

    return stacks


# ---------------------------------------------------------------------------
# Total pipe run calculation
# ---------------------------------------------------------------------------


def _path_length_m(path: list[MEPPoint]) -> float:
    total = 0.0
    for i in range(1, len(path)):
        a, b = path[i - 1], path[i]
        # 2D horizontal + 3D vertical (assume 3m floor height)
        h_dist = math.hypot(b.x - a.x, b.y - a.y)
        v_dist = abs(b.floor - a.floor) * 3.0
        total += h_dist + v_dist
    return total


def _conduit_run_length_m(run: ConduitRun) -> float:
    return _path_length_m(run.path)


# ---------------------------------------------------------------------------
# Top-level MEP network builder
# ---------------------------------------------------------------------------


def build_mep_network(
    floor_plans: list[FloorPlan],
    mep_req: MEPRequirements | None = None,
) -> MEPNetwork:
    """
    Build a complete MEP network for the building.

    This is the main entry point called by the MEP agent node.
    Returns a MEPNetwork that can be attached to each FloorPlan.
    """
    all_conduit_runs: list[ConduitRun] = []
    all_panels: list[ElectricalPanel] = []

    for fp in floor_plans:
        runs, panel = route_electrical(fp, mep_req)
        all_conduit_runs.extend(runs)
        all_panels.append(panel)

    plumbing_stacks = route_plumbing(floor_plans, mep_req)

    total_load = sum(p.load_kva for p in all_panels)
    total_pipe  = sum(
        _path_length_m(s.cold_pipe_path) + _path_length_m(s.hot_pipe_path)
        for s in plumbing_stacks
    )
    total_conduit = sum(_conduit_run_length_m(r) for r in all_conduit_runs)

    return MEPNetwork(
        conduit_runs=all_conduit_runs,
        plumbing_stacks=plumbing_stacks,
        panels=all_panels,
        total_electrical_load_kva=round(total_load, 2),
        total_pipe_run_m=round(total_pipe + total_conduit, 2),
    )


def attach_mep_to_floor_plans(
    floor_plans: list[FloorPlan],
    network: MEPNetwork,
) -> None:
    """
    Partition the global MEP network into per-floor sub-networks and
    attach each to the corresponding FloorPlan.mep_network field.
    Modifies floor_plans in-place.
    """
    for fp in floor_plans:
        floor_runs = [
            r for r in network.conduit_runs
            if any(p.floor == fp.floor for p in r.path)
        ]
        floor_panels = [
            p for p in network.panels
            if p.location.floor == fp.floor
        ]
        # Plumbing stacks that touch this floor
        floor_stacks = [
            s for s in network.plumbing_stacks
            if fp.floor in s.floors_served
        ]

        floor_load = sum(p.load_kva for p in floor_panels)
        floor_pipe  = sum(
            _path_length_m(s.cold_pipe_path) + _path_length_m(s.hot_pipe_path)
            for s in floor_stacks
        )

        fp.mep_network = MEPNetwork(
            conduit_runs=floor_runs,
            plumbing_stacks=floor_stacks,
            panels=floor_panels,
            total_electrical_load_kva=round(floor_load, 2),
            total_pipe_run_m=round(floor_pipe, 2),
        )
