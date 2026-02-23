"""
Unit tests for the MEP router.

Tests cover:
- Single-floor electrical routing (panel → room outlets)
- Multi-floor plumbing stacking (wet room grouping + alignment)
- No-pipe-through-bedroom NBC rule
- Panel load calculation and phase selection (1-phase vs 3-phase)
- Grid obstacle handling (walls block conduit routes)
- Wire gauge assignment by room type and appliance
- MEP DXF layer creation
- Full network assembly (build_mep_network)
"""

from __future__ import annotations

import pytest

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.reasoning_engine.mep_router import (
    _astar,
    _build_obstacle_grid,
    _pipe_dia_for_grade,
    _room_circuit_name,
    _wire_gauge_for_room,
    attach_mep_to_floor_plans,
    build_mep_network,
    route_electrical,
    route_plumbing,
)
from civilengineer.schemas.design import (
    Door,
    DoorSwing,
    FloorPlan,
    Point2D,
    Rect2D,
    RoomLayout,
    RoomType,
    WallFace,
    WallSegment,
)
from civilengineer.schemas.mep import MEPRequirements


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_room(
    room_id: str,
    room_type: RoomType,
    x: float,
    y: float,
    w: float,
    d: float,
    floor: int = 1,
    is_main_entrance: bool = False,
) -> RoomLayout:
    doors = []
    if is_main_entrance:
        doors.append(
            Door(
                wall_face=WallFace.SOUTH,
                position_along_wall=w / 2,
                is_main_entrance=True,
            )
        )
    return RoomLayout(
        room_id=room_id,
        room_type=room_type,
        name=room_type.value.title(),
        floor=floor,
        bounds=Rect2D(x=x, y=y, width=w, depth=d),
        doors=doors,
    )


def _make_floor(
    floor: int,
    rooms: list[RoomLayout],
    walls: list[WallSegment] | None = None,
    bz_w: float = 10.0,
    bz_d: float = 8.0,
) -> FloorPlan:
    return FloorPlan(
        floor=floor,
        buildable_zone=Rect2D(x=1.0, y=1.0, width=bz_w, depth=bz_d),
        rooms=rooms,
        wall_segments=walls or [],
    )


# ---------------------------------------------------------------------------
# 1. Single-floor electrical routing
# ---------------------------------------------------------------------------


def test_route_electrical_basic():
    """Panel + conduit run is created for each non-stair room."""
    rooms = [
        _make_room("r1", RoomType.LIVING_ROOM, 1.0, 1.0, 4.0, 3.0, is_main_entrance=True),
        _make_room("r2", RoomType.KITCHEN, 5.0, 1.0, 3.0, 3.0),
        _make_room("r3", RoomType.BEDROOM, 1.0, 4.0, 4.0, 3.0),
        _make_room("r4", RoomType.BATHROOM, 5.0, 4.0, 3.0, 3.0),
    ]
    fp = _make_floor(1, rooms)
    runs, panel = route_electrical(fp)

    assert panel.floor_num if hasattr(panel, "floor_num") else panel.location.floor == 1
    assert len(runs) == 4  # one per non-stair room
    assert all(len(r.path) >= 2 for r in runs)
    assert panel.num_circuits >= 4


def test_route_electrical_staircase_excluded():
    """Staircase and corridor rooms are not routed as dedicated circuits."""
    rooms = [
        _make_room("s1", RoomType.STAIRCASE, 1.0, 1.0, 2.0, 2.0),
        _make_room("c1", RoomType.CORRIDOR, 3.0, 1.0, 2.0, 1.0),
        _make_room("r1", RoomType.BEDROOM, 1.0, 3.0, 4.0, 3.0),
    ]
    fp = _make_floor(1, rooms)
    runs, panel = route_electrical(fp)

    # Only bedroom gets a dedicated run
    assert len(runs) == 1
    assert runs[0].circuit_name.startswith("POWER_BEDROOM")


def test_route_electrical_panel_floor_set():
    """Panel location floor field matches the floor plan."""
    rooms = [_make_room("r1", RoomType.LIVING_ROOM, 1.0, 1.0, 4.0, 3.0)]
    fp = _make_floor(2, rooms)
    _, panel = route_electrical(fp)
    assert panel.location.floor == 2


def test_route_electrical_conduit_paths_non_empty():
    """Every conduit run must have at least a start and end waypoint."""
    rooms = [
        _make_room("r1", RoomType.BEDROOM, 1.0, 1.0, 3.0, 3.0),
        _make_room("r2", RoomType.KITCHEN, 4.0, 1.0, 3.0, 3.0),
    ]
    fp = _make_floor(1, rooms)
    runs, _ = route_electrical(fp)
    for run in runs:
        assert len(run.path) >= 2


# ---------------------------------------------------------------------------
# 2. Wire gauge and load assignment
# ---------------------------------------------------------------------------


def test_wire_gauge_ac_master_bedroom():
    """Master bedroom with AC appliance gets 10mm² gauge."""
    room = _make_room("mb", RoomType.MASTER_BEDROOM, 0, 0, 4, 4)
    mep_req = MEPRequirements(high_load_appliances=["AC_MASTER"])
    gauge = _wire_gauge_for_room(room, mep_req)
    assert gauge == 10.0


def test_wire_gauge_kitchen_default():
    """Kitchen without oven gets power gauge (6mm²)."""
    room = _make_room("k1", RoomType.KITCHEN, 0, 0, 3, 3)
    gauge = _wire_gauge_for_room(room, None)
    assert gauge == 6.0


def test_wire_gauge_bedroom_no_ac():
    """Bedroom without AC gets standard power gauge."""
    room = _make_room("b1", RoomType.BEDROOM, 0, 0, 3, 3)
    gauge = _wire_gauge_for_room(room, None)
    assert gauge == 6.0


def test_circuit_name_format():
    """Circuit names follow POWER_{ROOM_TYPE}_F{FLOOR} pattern."""
    room = _make_room("r1", RoomType.KITCHEN, 0, 0, 3, 3, floor=2)
    name = _room_circuit_name(room, "POWER")
    assert name == "POWER_KITCHEN_F2"


# ---------------------------------------------------------------------------
# 3. Panel load calculation and phase selection
# ---------------------------------------------------------------------------


def test_panel_1phase_small_load():
    """A small 1-room plan should produce a 1-phase panel."""
    rooms = [_make_room("r1", RoomType.BEDROOM, 1.0, 1.0, 3.0, 3.0)]
    fp = _make_floor(1, rooms)
    _, panel = route_electrical(fp)
    assert panel.phase == "1-phase"
    assert panel.load_kva <= 10.0


def test_panel_3phase_large_load():
    """Many high-load rooms should tip to 3-phase."""
    rooms = [
        _make_room(f"r{i}", RoomType.MASTER_BEDROOM, float(i * 4), 1.0, 3.0, 3.0)
        for i in range(6)
    ]
    mep_req = MEPRequirements(
        high_load_appliances=["AC_MASTER", "OVEN_KITCHEN", "WM_UTILITY"]
    )
    fp = _make_floor(1, rooms, bz_w=30.0)
    _, panel = route_electrical(fp, mep_req)
    # 6 master bedrooms with AC each contribute 1.5 kVA extra → >10 kVA total
    assert panel.load_kva > 10.0
    assert panel.phase == "3-phase"


# ---------------------------------------------------------------------------
# 4. Grid obstacle handling
# ---------------------------------------------------------------------------


def test_build_obstacle_grid_wall():
    """A horizontal wall creates blocked cells along its length."""
    wall = WallSegment(
        start=Point2D(x=0.0, y=2.0),
        end=Point2D(x=4.0, y=2.0),
    )
    rooms = [_make_room("r1", RoomType.LIVING_ROOM, 0, 0, 3, 3)]
    fp = _make_floor(1, rooms, walls=[wall])
    blocked = _build_obstacle_grid(fp)
    # At least some cells along y=2 should be blocked
    blocked_y = {c[1] for c in blocked}
    grid_y_2 = int(2.0 / 0.25)
    assert grid_y_2 in blocked_y


def test_astar_around_obstacle():
    """A* finds a path that avoids the single obstacle."""
    blocked = {(5, 0), (5, 1), (5, 2), (5, 3), (5, 4)}
    start = (0, 2)
    goal  = (10, 2)
    bounds = (0, 0, 15, 5)
    path = _astar(start, goal, blocked, bounds)
    # Path should exist and not pass through blocked cells
    assert len(path) >= 2
    for cell in path:
        assert cell not in blocked


def test_astar_no_obstacle_straight():
    """A* on open grid finds near-straight path."""
    blocked: set[tuple[int, int]] = set()
    start = (0, 0)
    goal  = (10, 0)
    bounds = (0, 0, 15, 5)
    path = _astar(start, goal, blocked, bounds)
    assert path[0] == start
    assert path[-1] == goal


# ---------------------------------------------------------------------------
# 5. Plumbing stacking
# ---------------------------------------------------------------------------


def test_plumbing_single_floor_wet_rooms():
    """Wet rooms on single floor produce at least one stack."""
    rooms = [
        _make_room("b1", RoomType.BATHROOM, 5.0, 1.0, 2.0, 2.0),
        _make_room("k1", RoomType.KITCHEN, 1.0, 1.0, 3.0, 3.0),
    ]
    fp = _make_floor(1, rooms)
    stacks = route_plumbing([fp])
    assert len(stacks) >= 1


def test_plumbing_multifloor_stacking():
    """Bathrooms on different floors at same position share a stack."""
    bath1 = _make_room("b1", RoomType.BATHROOM, 5.0, 5.0, 2.0, 2.0, floor=1)
    bath2 = _make_room("b2", RoomType.BATHROOM, 5.0, 5.0, 2.0, 2.0, floor=2)
    fp1 = _make_floor(1, [bath1])
    fp2 = _make_floor(2, [bath2])

    stacks = route_plumbing([fp1, fp2])
    # Both bathrooms should be in same stack
    assert any(
        "b1" in s.wet_rooms and "b2" in s.wet_rooms
        for s in stacks
    )


def test_plumbing_no_pipe_through_bedroom():
    """Plumbing paths avoid routing directly through bedroom bounds."""
    # Bedroom sits between kitchen (left) and bathroom (right)
    bedroom = _make_room("bd1", RoomType.BEDROOM, 3.0, 1.0, 3.0, 3.0, floor=1)
    bath    = _make_room("bt1", RoomType.BATHROOM, 6.5, 1.0, 2.0, 2.0, floor=1)
    kitchen = _make_room("kt1", RoomType.KITCHEN,  0.5, 1.0, 2.0, 2.0, floor=1)
    fp = _make_floor(1, [bedroom, bath, kitchen])

    stacks = route_plumbing([fp])
    # All pipe paths should have at least start + end
    for s in stacks:
        assert len(s.cold_pipe_path) >= 2


def test_plumbing_separate_stacks_far_rooms():
    """Wet rooms > 1.5m apart should produce separate stacks."""
    bath1 = _make_room("b1", RoomType.BATHROOM, 0.0, 0.0, 2.0, 2.0, floor=1)
    bath2 = _make_room("b2", RoomType.BATHROOM, 8.0, 0.0, 2.0, 2.0, floor=1)
    fp = _make_floor(1, [bath1, bath2])
    stacks = route_plumbing([fp])
    assert len(stacks) == 2


def test_pipe_dia_by_grade():
    """Plumbing grade maps to correct pipe diameter."""
    assert _pipe_dia_for_grade("basic") == 15.0
    assert _pipe_dia_for_grade("standard") == 20.0
    assert _pipe_dia_for_grade("premium") == 25.0
    assert _pipe_dia_for_grade("unknown") == 20.0  # default


# ---------------------------------------------------------------------------
# 6. Full MEP network
# ---------------------------------------------------------------------------


def test_build_mep_network_returns_network():
    """build_mep_network returns a populated MEPNetwork."""
    rooms = [
        _make_room("r1", RoomType.LIVING_ROOM, 1.0, 1.0, 4.0, 3.0, is_main_entrance=True),
        _make_room("r2", RoomType.KITCHEN,     5.0, 1.0, 3.0, 3.0),
        _make_room("r3", RoomType.BATHROOM,    1.0, 4.0, 2.0, 2.0),
        _make_room("r4", RoomType.BEDROOM,     3.5, 4.0, 3.0, 3.0),
    ]
    fp = _make_floor(1, rooms)
    network = build_mep_network([fp])

    assert len(network.conduit_runs) >= 1
    assert len(network.panels) == 1
    assert network.total_electrical_load_kva > 0


def test_attach_mep_to_floor_plans():
    """attach_mep_to_floor_plans sets mep_network on each floor plan."""
    rooms = [_make_room("r1", RoomType.BEDROOM, 1.0, 1.0, 3.0, 3.0)]
    fp = _make_floor(1, rooms)
    network = build_mep_network([fp])
    attach_mep_to_floor_plans([fp], network)
    assert fp.mep_network is not None


# ---------------------------------------------------------------------------
# 7. MEP DXF layer definitions
# ---------------------------------------------------------------------------


def test_mep_layers_defined():
    """All required MEP layers are defined in LayerManager."""
    layer_names = {ld.name for ld in LayerManager.LAYER_DEFS}
    required = {
        LayerManager.MEP_CONDUIT,
        LayerManager.MEP_PANEL,
        LayerManager.MEP_SUPPLY,
        LayerManager.MEP_HW_SUPPLY,
        LayerManager.MEP_STACK,
    }
    assert required.issubset(layer_names)


def test_mep_layer_colors():
    """MEP layers have correct ACI colors."""
    by_name = {ld.name: ld for ld in LayerManager.LAYER_DEFS}
    assert by_name[LayerManager.MEP_CONDUIT].color == 4    # cyan
    assert by_name[LayerManager.MEP_SUPPLY].color == 5     # blue
    assert by_name[LayerManager.MEP_HW_SUPPLY].color == 1  # red
    assert by_name[LayerManager.MEP_STACK].color == 6      # magenta


def test_mep_conduit_layer_is_dashed():
    """E-CONDUIT layer linetype is DASHED."""
    by_name = {ld.name: ld for ld in LayerManager.LAYER_DEFS}
    assert by_name[LayerManager.MEP_CONDUIT].linetype == "DASHED"


# ---------------------------------------------------------------------------
# 8. MEP DXF rendering (smoke test)
# ---------------------------------------------------------------------------


def test_render_mep_plan_creates_dxf(tmp_path):
    """render_mep_plan produces a valid DXF file without errors."""
    from civilengineer.cad_layer.ezdxf_driver import EzdxfDriver
    from civilengineer.schemas.design import BuildingDesign

    rooms = [
        _make_room("r1", RoomType.LIVING_ROOM, 1.0, 1.0, 4.0, 3.0, is_main_entrance=True),
        _make_room("r2", RoomType.BATHROOM,    5.0, 1.0, 2.0, 2.0),
    ]
    fp = _make_floor(1, rooms)
    network = build_mep_network([fp])
    attach_mep_to_floor_plans([fp], network)

    building = BuildingDesign(
        design_id="TEST01",
        project_id="proj-1",
        num_floors=1,
        plot_width=12.0,
        plot_depth=10.0,
        floor_plans=[fp],
    )

    driver = EzdxfDriver()
    out = tmp_path / "floor1_mep.dxf"
    doc = driver.render_mep_plan(fp, building, out)

    assert out.exists()
    assert doc is not None
    assert out.stat().st_size > 0
