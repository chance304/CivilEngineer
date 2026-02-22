"""
Layout generator.

Converts a SolveResult (placed rooms with x, y, width, depth)
into a list of FloorPlan objects with full room geometry:
  - RoomLayout with bounds (Rect2D in plot coordinates)
  - External wall flags (room touches buildable-zone edge)
  - Windows on every external wall face (centered, 1.2 m wide)
  - One door per room (opposite to primary external wall, or interior face)

Coordinate system
-----------------
PlacedRoom x/y are relative to the buildable zone origin.
RoomLayout.bounds are in plot coordinates:
    bounds.x = buildable_zone.x + placed.x
    bounds.y = buildable_zone.y + placed.y

Usage
-----
    from civilengineer.geometry_engine.layout_generator import generate_floor_plans
    floor_plans = generate_floor_plans(solve_result, requirements, plot_info, setbacks)
"""

from __future__ import annotations

from civilengineer.reasoning_engine.constraint_solver import PlacedRoom, SolveResult
from civilengineer.schemas.design import (
    DesignRequirements,
    Door,
    DoorSwing,
    FloorPlan,
    Rect2D,
    RoomLayout,
    RoomType,
    WallFace,
    Window,
)
from civilengineer.schemas.project import PlotInfo

# Tolerance for "touching zone boundary" (metres)
_BOUNDARY_TOL = 0.05

# Standard window width (metres)
_WINDOW_WIDTH = 1.2

# Standard door widths
_DOOR_WIDTH_MAIN    = 1.2   # main entrance
_DOOR_WIDTH_BEDROOM = 0.9   # bedroom / interior
_DOOR_WIDTH_SERVICE = 0.8   # bathroom / toilet

# Room types that are habitable (get windows)
_HABITABLE = frozenset({
    RoomType.MASTER_BEDROOM,
    RoomType.BEDROOM,
    RoomType.LIVING_ROOM,
    RoomType.DINING_ROOM,
    RoomType.KITCHEN,
    RoomType.HOME_OFFICE,
    RoomType.POOJA_ROOM,
    RoomType.OTHER,
})


def generate_floor_plans(
    solve_result: SolveResult,
    requirements: DesignRequirements,
    plot_info: PlotInfo,
    setbacks: tuple[float, float, float, float],
    floor_height: float = 3.0,
) -> list[FloorPlan]:
    """
    Build a list of FloorPlan objects from SolveResult.

    Args:
        solve_result : output of constraint_solver.solve_layout()
        requirements : DesignRequirements (for jurisdiction, vastu flags)
        plot_info    : PlotInfo (for plot dimensions)
        setbacks     : (front, rear, left, right) in metres
        floor_height : floor-to-ceiling height (metres)

    Returns:
        List of FloorPlan — one per floor, ordered floor 1 → N.
    """
    zone = solve_result.buildable_zone
    front, rear, left, right = setbacks

    # Group placed rooms by floor
    by_floor: dict[int, list[PlacedRoom]] = {}
    for pr in solve_result.placed_rooms:
        by_floor.setdefault(pr.floor, []).append(pr)

    floor_plans: list[FloorPlan] = []

    for floor_num in sorted(by_floor.keys()):
        rooms_on_floor = by_floor[floor_num]
        room_layouts = []

        for idx, pr in enumerate(rooms_on_floor):
            room_id = f"R{floor_num}_{idx + 1:02d}_{pr.room_req.room_type.value[:4].upper()}"

            # Convert zone-relative coords → plot coords
            bounds = Rect2D(
                x=zone.x + pr.x,
                y=zone.y + pr.y,
                width=pr.width,
                depth=pr.depth,
            )

            # Detect external wall faces
            ext_south = _near(bounds.y, zone.y, _BOUNDARY_TOL)
            ext_north = _near(bounds.y + bounds.depth, zone.y + zone.depth, _BOUNDARY_TOL)
            ext_west  = _near(bounds.x, zone.x, _BOUNDARY_TOL)
            ext_east  = _near(bounds.x + bounds.width, zone.x + zone.width, _BOUNDARY_TOL)

            # Windows on external faces (habitable rooms only)
            windows: list[Window] = []
            if pr.room_req.room_type in _HABITABLE:
                if ext_south:
                    windows.append(_center_window(bounds.width, WallFace.SOUTH))
                if ext_north:
                    windows.append(_center_window(bounds.width, WallFace.NORTH))
                if ext_west:
                    windows.append(_center_window(bounds.depth, WallFace.WEST))
                if ext_east:
                    windows.append(_center_window(bounds.depth, WallFace.EAST))

            # Door placement
            door = _place_door(pr, bounds, ext_south, ext_north, ext_west, ext_east, floor_num)
            doors = [door] if door else []

            display_name = _room_display_name(pr.room_req.room_type, idx, rooms_on_floor)

            room_layouts.append(RoomLayout(
                room_id=room_id,
                room_type=pr.room_req.room_type,
                name=pr.room_req.name or display_name,
                floor=floor_num,
                bounds=bounds,
                doors=doors,
                windows=windows,
                is_external_wall_north=ext_north,
                is_external_wall_south=ext_south,
                is_external_wall_east=ext_east,
                is_external_wall_west=ext_west,
                staircase_spec=pr.staircase_spec,
            ))

        floor_plans.append(FloorPlan(
            floor=floor_num,
            floor_height=floor_height,
            buildable_zone=zone,
            rooms=room_layouts,
            wall_segments=[],   # populated by wall_builder
        ))

    return floor_plans


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _near(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _center_window(wall_length: float, face: WallFace) -> Window:
    """Return a centered window on a wall of given length."""
    win_w = min(_WINDOW_WIDTH, wall_length * 0.6)
    pos = (wall_length - win_w) / 2
    return Window(
        wall_face=face,
        position_along_wall=round(pos, 2),
        width=round(win_w, 2),
        height=1.2,
        sill_height=0.9,
    )


def _place_door(
    pr: PlacedRoom,
    bounds: Rect2D,
    ext_south: bool,
    ext_north: bool,
    ext_west: bool,
    ext_east: bool,
    floor_num: int,
) -> Door | None:
    """
    Decide which wall face gets a door and place it centered on that face.

    Priority for non-service rooms:
        - Ground floor: prefer south (road side) or first internal face
        - Upper floors: prefer internal face (not external wall)
    For service rooms (bathroom/toilet): always on an internal face.
    """
    rtype = pr.room_req.room_type
    is_service = rtype in (RoomType.BATHROOM, RoomType.TOILET)
    is_main    = rtype == RoomType.LIVING_ROOM and floor_num == 1

    door_width = (
        _DOOR_WIDTH_MAIN if is_main
        else _DOOR_WIDTH_SERVICE if is_service
        else _DOOR_WIDTH_BEDROOM
    )

    # Face preference order
    if is_service:
        # Avoid external faces for service rooms
        preference = [
            (WallFace.NORTH, not ext_north, bounds.width),
            (WallFace.EAST,  not ext_east,  bounds.depth),
            (WallFace.WEST,  not ext_west,  bounds.depth),
            (WallFace.SOUTH, not ext_south, bounds.width),
        ]
    elif floor_num == 1:
        # Ground floor: south (road side) first
        preference = [
            (WallFace.SOUTH, True, bounds.width),
            (WallFace.EAST,  True, bounds.depth),
            (WallFace.WEST,  True, bounds.depth),
            (WallFace.NORTH, True, bounds.width),
        ]
    else:
        # Upper floors: internal face preferred
        preference = [
            (WallFace.NORTH, not ext_north, bounds.width),
            (WallFace.SOUTH, not ext_south, bounds.width),
            (WallFace.EAST,  not ext_east,  bounds.depth),
            (WallFace.WEST,  not ext_west,  bounds.depth),
        ]

    for face, condition, wall_len in preference:
        if condition and wall_len >= door_width:
            pos = (wall_len - door_width) / 2
            return Door(
                wall_face=face,
                position_along_wall=round(pos, 2),
                width=door_width,
                swing=DoorSwing.LEFT,
                is_main_entrance=is_main and face == WallFace.SOUTH,
            )

    return None


def _room_display_name(rtype: RoomType, idx: int, floor_rooms: list[PlacedRoom]) -> str:
    """Generate a display label, numbering rooms of the same type."""
    same_type = [r for r in floor_rooms if r.room_req.room_type == rtype]
    base = rtype.value.replace("_", " ").title()
    if len(same_type) == 1:
        return base
    pos = next(i for i, r in enumerate(same_type)
               if r.room_req.room_type == rtype
               and r.x == floor_rooms[idx].x
               and r.y == floor_rooms[idx].y)
    return f"{base} {pos + 1}"
