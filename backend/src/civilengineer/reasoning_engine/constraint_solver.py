"""
OR-Tools CP-SAT constraint solver for room placement.

Two-phase approach
------------------
Phase A — Room sizing:
    Determine target (width, depth) for every requested room, respecting:
    - NBC 2020 minimum area rules
    - NBC 2020 minimum dimension rules
    - Default aspect-ratio preferences per room type
    - Custom min_area from RoomRequirement (user override)

Phase B — Placement (CP-SAT NoOverlap2D):
    Given fixed room dimensions, find (x, y) positions so that:
    - Every room fits entirely within the buildable zone
    - No two rooms overlap
    Objective: pack rooms as tightly as possible (minimise bounding box).

Multi-floor distribution
------------------------
Rooms are assigned to floors before solving:
    Floor 1: living, dining, kitchen, service rooms, garage, staircase
    Floor 2+: bedrooms, bathrooms, home office, staircase (repeated)
    Rooms with an explicit floor= field keep that floor.
    If num_floors == 1, everything goes to floor 1.

If a floor's rooms cannot fit in the buildable zone, the solver reports
UNSAT for that floor and lists the unplaced rooms in SolveResult.

Usage
-----
    from civilengineer.reasoning_engine.constraint_solver import solve_layout
    result = solve_layout(requirements, buildable_zone, rules)
    if result.status == SolveStatus.SAT:
        for room in result.placed_rooms:
            print(room.room_req.room_type, room.x, room.y, room.width, room.depth)
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum

from pydantic import BaseModel

from civilengineer.schemas.design import (
    DesignRequirements,
    Rect2D,
    RoomRequirement,
    RoomType,
)
from civilengineer.schemas.rules import DesignRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Integer scaling factor — 1 unit = 0.1 m (10 cm precision)
# ---------------------------------------------------------------------------
_SCALE = 10

# ---------------------------------------------------------------------------
# Default target dimensions (width, depth) in metres per room type
# These satisfy NBC 2020 NP-KTM minimums with comfortable margins.
# ---------------------------------------------------------------------------
_DEFAULT_DIMS: dict[RoomType, tuple[float, float]] = {
    RoomType.MASTER_BEDROOM: (3.6, 3.6),   # 12.96 sqm  (min 12.0)
    RoomType.BEDROOM:        (3.2, 3.2),   # 10.24 sqm  (min 9.5)
    RoomType.LIVING_ROOM:    (4.5, 3.6),   # 16.20 sqm  (min 13.5)
    RoomType.DINING_ROOM:    (3.2, 3.0),   # 9.60 sqm   (min 9.0)
    RoomType.KITCHEN:        (3.0, 2.5),   # 7.50 sqm   (min 5.0, dim 2.4)
    RoomType.BATHROOM:       (2.0, 1.8),   # 3.60 sqm   (min 2.5)
    RoomType.TOILET:         (1.5, 1.2),   # 1.80 sqm   (min 1.2)
    RoomType.STAIRCASE:      (2.0, 2.4),   # 4.80 sqm   (min 4.5)
    RoomType.CORRIDOR:       (1.2, 4.0),   # 4.80 sqm
    RoomType.STORE:          (2.0, 2.0),   # 4.00 sqm
    RoomType.POOJA_ROOM:     (2.0, 2.0),   # 4.00 sqm   (min 3.0)
    RoomType.GARAGE:         (3.0, 5.5),   # 16.50 sqm  (min 15.0)
    RoomType.HOME_OFFICE:    (3.0, 2.8),   # 8.40 sqm   (min 7.5)
    RoomType.BALCONY:        (1.5, 3.0),   # 4.50 sqm
    RoomType.TERRACE:        (3.0, 4.0),   # 12.00 sqm
    RoomType.OTHER:          (2.5, 2.5),   # 6.25 sqm
}

# Minimum dimension (shorter side) per room type — from NBC 2020 rules
_MIN_DIM: dict[RoomType, float] = {
    RoomType.MASTER_BEDROOM: 3.0,
    RoomType.BEDROOM:        2.8,
    RoomType.LIVING_ROOM:    3.0,
    RoomType.DINING_ROOM:    2.5,
    RoomType.KITCHEN:        2.4,
    RoomType.BATHROOM:       1.2,
    RoomType.TOILET:         1.0,
    RoomType.STAIRCASE:      1.5,  # clear width
    RoomType.CORRIDOR:       1.2,
}

# Rooms that belong on the ground floor by default
_GROUND_FLOOR_TYPES = frozenset({
    RoomType.LIVING_ROOM,
    RoomType.DINING_ROOM,
    RoomType.KITCHEN,
    RoomType.GARAGE,
    RoomType.STORE,
    RoomType.POOJA_ROOM,
    RoomType.BALCONY,
})

# Rooms that belong on upper floors by default
_UPPER_FLOOR_TYPES = frozenset({
    RoomType.MASTER_BEDROOM,
    RoomType.BEDROOM,
    RoomType.HOME_OFFICE,
    RoomType.TERRACE,
})


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class SolveStatus(StrEnum):
    SAT     = "SAT"      # All rooms placed
    PARTIAL = "PARTIAL"  # Some rooms placed; unplaced rooms listed
    UNSAT   = "UNSAT"    # No feasible placement found
    TIMEOUT = "TIMEOUT"  # Solver ran out of time


class SizedRoom(BaseModel):
    """A room with computed target dimensions (pre-placement)."""
    room_req: RoomRequirement
    floor: int
    width: float   # metres
    depth: float   # metres

    @property
    def area(self) -> float:
        return self.width * self.depth


class PlacedRoom(BaseModel):
    """A room with both dimensions and position resolved."""
    room_req: RoomRequirement
    floor: int
    x: float       # metres from buildable zone origin
    y: float
    width: float   # metres
    depth: float   # metres

    @property
    def area(self) -> float:
        return self.width * self.depth


class SolveResult(BaseModel):
    status: SolveStatus
    placed_rooms: list[PlacedRoom]
    unplaced_rooms: list[RoomRequirement]
    warnings: list[str]
    solver_time_s: float
    buildable_zone: Rect2D
    floors_solved: list[int]   # floor numbers that had a feasible solution


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve_layout(
    requirements: DesignRequirements,
    buildable_zone: Rect2D,
    rules: list[DesignRule],
    timeout_s: float = 30.0,
) -> SolveResult:
    """
    Place all rooms from requirements within buildable_zone.

    Args:
        requirements   : DesignRequirements from the interview
        buildable_zone : computed by input_layer.enricher
        rules          : active DesignRule list (used to validate min sizes)
        timeout_s      : CP-SAT wall-clock time limit per floor

    Returns:
        SolveResult with placed_rooms, unplaced_rooms, status, timing.
    """
    t0 = time.monotonic()
    warnings: list[str] = []

    rooms_with_floors = _assign_floors(requirements, warnings)
    sized_rooms = _size_rooms(rooms_with_floors, rules, buildable_zone, warnings)

    all_placed: list[PlacedRoom] = []
    all_unplaced: list[RoomRequirement] = []
    floors_solved: list[int] = []

    # Group by floor and solve each floor independently
    floors: dict[int, list[SizedRoom]] = {}
    for sr in sized_rooms:
        floors.setdefault(sr.floor, []).append(sr)

    # Keep staircase in sync across all floors (same x,y on every floor)
    staircase_position: tuple[float, float] | None = None

    for floor_num in sorted(floors.keys()):
        floor_rooms = floors[floor_num]
        placed, unplaced, staircase_position = _solve_floor(
            floor_num, floor_rooms, buildable_zone,
            staircase_position, timeout_s, warnings,
        )
        all_placed.extend(placed)
        all_unplaced.extend(unplaced)
        if placed:
            floors_solved.append(floor_num)

    elapsed = time.monotonic() - t0

    if not all_placed:
        status = SolveStatus.UNSAT
    elif all_unplaced:
        status = SolveStatus.PARTIAL
    else:
        status = SolveStatus.SAT

    return SolveResult(
        status=status,
        placed_rooms=all_placed,
        unplaced_rooms=all_unplaced,
        warnings=warnings,
        solver_time_s=elapsed,
        buildable_zone=buildable_zone,
        floors_solved=floors_solved,
    )


# ---------------------------------------------------------------------------
# Floor assignment
# ---------------------------------------------------------------------------


def _assign_floors(
    requirements: DesignRequirements,
    warnings: list[str],
) -> list[tuple[RoomRequirement, int]]:
    """
    Return (room_req, floor) pairs.

    Rooms with an explicit floor= keep that floor.
    Others are distributed using ground/upper floor heuristics.
    Staircase is assigned to ALL floors.
    """
    result: list[tuple[RoomRequirement, int]] = []
    num_floors = requirements.num_floors

    # Counters for fair distribution of unassigned service rooms
    bathroom_floor: dict[int, int] = {f: 0 for f in range(1, num_floors + 1)}

    staircase_rooms: list[RoomRequirement] = []
    other_rooms: list[RoomRequirement] = []

    for req in requirements.rooms:
        if req.room_type == RoomType.STAIRCASE:
            staircase_rooms.append(req)
        else:
            other_rooms.append(req)

    # Staircase goes on every floor (same footprint repeated)
    # For single-floor buildings, only add a staircase if explicitly requested.
    stair_req = (
        staircase_rooms[0] if staircase_rooms
        else RoomRequirement(room_type=RoomType.STAIRCASE)
    )
    if staircase_rooms and len(staircase_rooms) > 1:
        warnings.append("Multiple staircases specified; only first used.")

    if staircase_rooms or num_floors > 1:
        for floor in range(1, num_floors + 1):
            result.append((stair_req, floor))

    for req in other_rooms:
        if req.floor is not None:
            result.append((req, req.floor))
            continue

        if num_floors == 1:
            result.append((req, 1))
            continue

        rtype = req.room_type

        if rtype in _GROUND_FLOOR_TYPES:
            result.append((req, 1))
        elif rtype in _UPPER_FLOOR_TYPES:
            # Distribute bedrooms across upper floors
            upper_floor = _pick_upper_floor(result, num_floors)
            result.append((req, upper_floor))
        elif rtype in (RoomType.BATHROOM, RoomType.TOILET):
            # Distribute bathrooms: 1 per floor starting with ground
            floor_with_fewest = min(bathroom_floor, key=lambda f: bathroom_floor[f])
            bathroom_floor[floor_with_fewest] += 1
            result.append((req, floor_with_fewest))
        else:
            # Corridors, store, other → ground floor
            result.append((req, 1))

    return result


def _pick_upper_floor(
    current: list[tuple[RoomRequirement, int]],
    num_floors: int,
) -> int:
    """Pick the upper floor with fewest rooms assigned so far."""
    counts: dict[int, int] = {f: 0 for f in range(2, num_floors + 1)}
    for _, f in current:
        if f >= 2:
            counts[f] = counts.get(f, 0) + 1
    return min(counts, key=lambda f: counts[f])


# ---------------------------------------------------------------------------
# Room sizing (Phase A)
# ---------------------------------------------------------------------------


def _dims_from_rules(rules: list[DesignRule]) -> dict[str, tuple[float, float]]:
    """
    Extract per-room-type default dimensions from ``room_default_dim`` rules.

    Rules seeded via ``scripts/seed_jurisdiction_rules.py`` carry
    ``rule_type="room_default_dim"`` and store the target width/depth in
    ``conditions`` (keys: ``"width"``, ``"depth"``).  Falls back to
    ``numeric_value`` for the missing dimension.

    Returns a mapping of room_type string → (width_m, depth_m).
    """
    result: dict[str, tuple[float, float]] = {}
    for rule in rules:
        if rule.rule_type != "room_default_dim":
            continue
        if not rule.applies_to or rule.numeric_value is None:
            continue
        w: float = rule.conditions.get("width", rule.numeric_value)
        d: float = rule.conditions.get("depth", rule.numeric_value)
        for room_type in rule.applies_to:
            result[room_type] = (float(w), float(d))
    return result


def _size_rooms(
    rooms_with_floors: list[tuple[RoomRequirement, int]],
    rules: list[DesignRule],
    buildable_zone: Rect2D,
    warnings: list[str],
) -> list[SizedRoom]:
    """
    Determine target (width, depth) for every room.

    Rules consulted for min_area and min_dimension overrides.
    User-supplied min_area on RoomRequirement wins over rules.
    """
    # Build lookup: rule_type → {room_type: value}
    min_area_rules: dict[str, float] = {}
    min_dim_rules: dict[str, float] = {}
    for rule in rules:
        if rule.rule_type == "min_area" and rule.numeric_value is not None:
            for app in rule.applies_to:
                min_area_rules[app] = max(
                    min_area_rules.get(app, 0.0), rule.numeric_value
                )
        if rule.rule_type == "min_dimension" and rule.numeric_value is not None:
            for app in rule.applies_to:
                min_dim_rules[app] = max(
                    min_dim_rules.get(app, 0.0), rule.numeric_value
                )

    # Merge rule-derived default dimensions over the hardcoded table.
    # room_default_dim rules (seeded from _DEFAULT_DIMS via seed script) override
    # the built-in values when available, making the solver jurisdiction-aware.
    rule_dims = _dims_from_rules(rules)

    sized: list[SizedRoom] = []
    for req, floor in rooms_with_floors:
        rtype = req.room_type
        rtype_str = rtype.value

        # Target dimensions: rule-derived dims take priority over hardcoded defaults
        target_w, target_d = rule_dims.get(rtype_str) or _DEFAULT_DIMS.get(rtype, (2.5, 2.5))

        # Apply min_area constraint
        req_min_area = req.min_area or min_area_rules.get(rtype_str, 0.0)
        if req_min_area > 0 and target_w * target_d < req_min_area:
            # Scale up while preserving aspect ratio
            scale = (req_min_area / (target_w * target_d)) ** 0.5
            target_w *= scale
            target_d *= scale

        # Apply min_dimension constraint
        min_dim = min_dim_rules.get(rtype_str) or _MIN_DIM.get(rtype, 0.0)
        if min_dim > 0:
            if target_w < min_dim:
                target_w = min_dim
            if target_d < min_dim:
                target_d = min_dim

        # Clamp to buildable zone size (prevent obviously impossible rooms)
        if target_w > buildable_zone.width * 0.95:
            warnings.append(
                f"Room {rtype_str} target width {target_w:.1f}m "
                f"exceeds 95% of buildable zone width {buildable_zone.width:.1f}m; "
                "clamped."
            )
            target_w = buildable_zone.width * 0.90

        if target_d > buildable_zone.depth * 0.95:
            warnings.append(
                f"Room {rtype_str} target depth {target_d:.1f}m "
                f"exceeds 95% of buildable zone depth {buildable_zone.depth:.1f}m; "
                "clamped."
            )
            target_d = buildable_zone.depth * 0.90

        # Round to 0.1 m
        target_w = round(target_w, 1)
        target_d = round(target_d, 1)

        sized.append(SizedRoom(room_req=req, floor=floor, width=target_w, depth=target_d))

    return sized


# ---------------------------------------------------------------------------
# CP-SAT placement (Phase B)
# ---------------------------------------------------------------------------


def _solve_floor(
    floor_num: int,
    sized_rooms: list[SizedRoom],
    zone: Rect2D,
    staircase_position: tuple[float, float] | None,
    timeout_s: float,
    warnings: list[str],
) -> tuple[list[PlacedRoom], list[RoomRequirement], tuple[float, float] | None]:
    """
    Place all rooms on one floor using CP-SAT NoOverlap2D.

    Returns (placed_rooms, unplaced_rooms, staircase_xy).
    staircase_xy is forwarded so all floors share the same staircase position.
    """
    from ortools.sat.python import cp_model  # noqa: PLC0415 — lazy import

    zone_w_i = int(zone.width * _SCALE)
    zone_d_i = int(zone.depth * _SCALE)

    if not sized_rooms:
        return [], [], staircase_position

    model = cp_model.CpModel()

    x_vars: list = []
    y_vars: list = []
    x_ivars: list = []
    y_ivars: list = []

    staircase_indices: list[int] = []

    for i, sr in enumerate(sized_rooms):
        w_i = max(1, int(sr.width * _SCALE))
        d_i = max(1, int(sr.depth * _SCALE))

        # Guard: room must fit in zone
        if w_i > zone_w_i or d_i > zone_d_i:
            warnings.append(
                f"Floor {floor_num}: {sr.room_req.room_type.value} "
                f"({sr.width:.1f}×{sr.depth:.1f}m) does not fit in "
                f"buildable zone ({zone.width:.1f}×{zone.depth:.1f}m); skipped."
            )
            # Skip — will appear in unplaced_rooms via absence from placed list
            x_vars.append(None)
            y_vars.append(None)
            x_ivars.append(None)
            y_ivars.append(None)
            continue

        if sr.room_req.room_type == RoomType.STAIRCASE and staircase_position is not None:
            # Fix staircase to same position as floor 1
            sx_i = int(staircase_position[0] * _SCALE)
            sy_i = int(staircase_position[1] * _SCALE)
            # Clamp if zone shifted
            sx_i = max(0, min(sx_i, zone_w_i - w_i))
            sy_i = max(0, min(sy_i, zone_d_i - d_i))
            x = model.NewConstant(sx_i)
            y = model.NewConstant(sy_i)
        else:
            x = model.NewIntVar(0, zone_w_i - w_i, f"x_{floor_num}_{i}")
            y = model.NewIntVar(0, zone_d_i - d_i, f"y_{floor_num}_{i}")

        xi = model.NewIntervalVar(x, w_i, x + w_i, f"xi_{floor_num}_{i}")
        yi = model.NewIntervalVar(y, d_i, y + d_i, f"yi_{floor_num}_{i}")

        x_vars.append(x)
        y_vars.append(y)
        x_ivars.append(xi)
        y_ivars.append(yi)

        if sr.room_req.room_type == RoomType.STAIRCASE:
            staircase_indices.append(i)

    # Filter out skipped rooms (None entries)
    valid_x_ivars = [v for v in x_ivars if v is not None]
    valid_y_ivars = [v for v in y_ivars if v is not None]

    if len(valid_x_ivars) > 1:
        model.AddNoOverlap2D(valid_x_ivars, valid_y_ivars)

    # Objective: pack rooms toward origin (minimise max x+y)
    if valid_x_ivars:
        max_x = model.NewIntVar(0, zone_w_i, f"max_x_{floor_num}")
        max_y = model.NewIntVar(0, zone_d_i, f"max_y_{floor_num}")
        for i, sr in enumerate(sized_rooms):
            if x_vars[i] is None:
                continue
            w_i = max(1, int(sr.width * _SCALE))
            d_i = max(1, int(sr.depth * _SCALE))
            model.Add(x_vars[i] + w_i <= max_x)
            model.Add(y_vars[i] + d_i <= max_y)
        model.Minimize(max_x + max_y)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_s
    solver.parameters.num_search_workers = 1  # deterministic

    status = solver.Solve(model)

    placed: list[PlacedRoom] = []
    unplaced: list[RoomRequirement] = []
    new_staircase_position = staircase_position

    cp_sat_ok = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    for i, sr in enumerate(sized_rooms):
        if x_vars[i] is None:
            unplaced.append(sr.room_req)
            continue

        if not cp_sat_ok:
            unplaced.append(sr.room_req)
            continue

        x_val = solver.Value(x_vars[i]) / _SCALE
        y_val = solver.Value(y_vars[i]) / _SCALE

        placed.append(PlacedRoom(
            room_req=sr.room_req,
            floor=floor_num,
            x=x_val,
            y=y_val,
            width=sr.width,
            depth=sr.depth,
        ))

        if sr.room_req.room_type == RoomType.STAIRCASE and staircase_position is None:
            new_staircase_position = (x_val, y_val)

    if not cp_sat_ok:
        status_name = {
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.UNKNOWN:    "TIMEOUT",
        }.get(status, f"status={status}")
        warnings.append(
            f"Floor {floor_num}: CP-SAT returned {status_name}. "
            f"{len(sized_rooms)} rooms cannot fit in "
            f"{zone.width:.1f}×{zone.depth:.1f}m buildable zone."
        )

    logger.debug(
        "Floor %d: placed %d / %d rooms in %.2fs",
        floor_num, len(placed), len(sized_rooms), solver.WallTime(),
    )

    return placed, unplaced, new_staircase_position
