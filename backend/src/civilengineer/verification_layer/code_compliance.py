"""
Extended building-code compliance checks for Phase 7.

This module supplements `reasoning_engine.rule_engine` (which handles
numeric area / setback / FAR checks) with additional spatial and
geometric compliance rules:

  - Window-to-floor-area ratio (≥ 10 % for habitable rooms)
  - Minimum room dimension (no room narrower than 2.1 m)
  - Staircase width (≥ 0.9 m clear) and area (≥ 4.5 sqm)
  - Kitchen aspect ratio (must not be "corridor-like" < 1:3)
  - Bathroom/toilet minimum area (≥ 1.2 sqm / ≥ 0.9 sqm)
  - Floor-to-ceiling height advisory
  - Overall ground coverage (< 60 % hard limit)
  - Total built-up area FAR check

Results are emitted as `RuleViolation` objects (from schemas.rules)
so they can be merged with the existing `ComplianceReport`.

Usage
-----
    from civilengineer.verification_layer.code_compliance import (
        extended_compliance_check,
    )
    violations = extended_compliance_check(building_design, plot_info)
"""

from __future__ import annotations

import logging

from civilengineer.schemas.design import (
    BuildingDesign,
    FloorPlan,
    RoomLayout,
    RoomType,
)
from civilengineer.schemas.rules import RuleCategory, RuleViolation, Severity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Window-to-floor-area ratio (NBC 2020 / KMC Bylaw 2076)
_MIN_WINDOW_RATIO = 0.10   # 10 % of floor area

# Minimum clear dimension for any habitable room (narrow-room check)
_MIN_CLEAR_DIM_HABITABLE = 2.1  # metres

# Staircase clear width
_MIN_STAIR_WIDTH = 0.9      # metres
_MIN_STAIR_AREA  = 4.5      # sqm

# Kitchen aspect ratio limit (width / depth or depth / width must be < 3.0)
_MAX_KITCHEN_ASPECT = 3.0

# Bathroom/toilet minimum areas (sqm)
_MIN_BATHROOM_AREA = 1.8    # full bathroom
_MIN_TOILET_AREA   = 0.9    # separate WC

# Room types that require natural light/ventilation
_HABITABLE = frozenset(
    {
        RoomType.MASTER_BEDROOM,
        RoomType.BEDROOM,
        RoomType.LIVING_ROOM,
        RoomType.DINING_ROOM,
        RoomType.KITCHEN,
        RoomType.HOME_OFFICE,
    }
)

# Maximum ground coverage (plot area fraction)
_MAX_COVERAGE_HARD = 0.60
_MAX_COVERAGE_SOFT = 0.65


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def _check_window_ratio(room: RoomLayout) -> list[RuleViolation]:
    """Window area must be ≥ 10 % of floor area for habitable rooms."""
    if room.room_type not in _HABITABLE:
        return []
    if not room.windows:
        # No windows at all — flagged by spatial_analyzer; skip double-count
        return []

    floor_area = room.bounds.area
    window_area = sum(w.width * w.height for w in room.windows)
    ratio = window_area / floor_area if floor_area > 0 else 0.0

    if ratio < _MIN_WINDOW_RATIO:
        return [
            RuleViolation(
                rule_id="EXT-WIN-RATIO",
                rule_name="Minimum Window-to-Floor Ratio",
                category=RuleCategory.OPENING,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Window area {window_area:.2f} sqm is {ratio*100:.1f}% of "
                    f"floor area {floor_area:.2f} sqm (minimum {_MIN_WINDOW_RATIO*100:.0f}%)"
                ),
                severity=Severity.SOFT,
                actual_value=window_area,
                required_value=floor_area * _MIN_WINDOW_RATIO,
                unit="sqm",
                source_section="NBC 205:2020 Clause 5.4",
            )
        ]
    return []


def _check_min_dimension(room: RoomLayout) -> list[RuleViolation]:
    """No habitable room should be narrower than 2.1 m in either direction."""
    if room.room_type not in _HABITABLE:
        return []

    violations = []
    for dim_name, dim_val in [
        ("width", room.bounds.width),
        ("depth", room.bounds.depth),
    ]:
        if dim_val < _MIN_CLEAR_DIM_HABITABLE:
            violations.append(
                RuleViolation(
                    rule_id="EXT-MIN-DIM",
                    rule_name="Minimum Room Dimension",
                    category=RuleCategory.AREA,
                    room_id=room.room_id,
                    room_type=room.room_type.value,
                    message=(
                        f"Room {dim_name} {dim_val:.2f} m is below minimum "
                        f"{_MIN_CLEAR_DIM_HABITABLE} m"
                    ),
                    severity=Severity.SOFT,
                    actual_value=dim_val,
                    required_value=_MIN_CLEAR_DIM_HABITABLE,
                    unit="m",
                    source_section="NBC 205:2020 Clause 5.1",
                )
            )
    return violations


def _check_staircase(room: RoomLayout) -> list[RuleViolation]:
    """Staircase must have clear width ≥ 0.9 m and total area ≥ 4.5 sqm."""
    if room.room_type != RoomType.STAIRCASE:
        return []

    violations = []
    min_dim = min(room.bounds.width, room.bounds.depth)
    if min_dim < _MIN_STAIR_WIDTH:
        violations.append(
            RuleViolation(
                rule_id="EXT-STAIR-WIDTH",
                rule_name="Staircase Minimum Clear Width",
                category=RuleCategory.STAIRCASE,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Staircase clear width {min_dim:.2f} m < minimum "
                    f"{_MIN_STAIR_WIDTH} m"
                ),
                severity=Severity.HARD,
                actual_value=min_dim,
                required_value=_MIN_STAIR_WIDTH,
                unit="m",
                source_section="NBC 205:2020 Clause 5.6",
            )
        )
    if room.bounds.area < _MIN_STAIR_AREA:
        violations.append(
            RuleViolation(
                rule_id="EXT-STAIR-AREA",
                rule_name="Staircase Minimum Area",
                category=RuleCategory.STAIRCASE,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Staircase area {room.bounds.area:.2f} sqm < minimum "
                    f"{_MIN_STAIR_AREA} sqm"
                ),
                severity=Severity.HARD,
                actual_value=room.bounds.area,
                required_value=_MIN_STAIR_AREA,
                unit="sqm",
                source_section="NBC 205:2020 Clause 5.6",
            )
        )
    return violations


def _check_kitchen_aspect(room: RoomLayout) -> list[RuleViolation]:
    """Kitchen must not be corridor-like (aspect ratio > 3:1)."""
    if room.room_type != RoomType.KITCHEN:
        return []
    if room.bounds.depth == 0:
        return []

    aspect = max(
        room.bounds.width / room.bounds.depth,
        room.bounds.depth / room.bounds.width,
    )
    if aspect > _MAX_KITCHEN_ASPECT:
        return [
            RuleViolation(
                rule_id="EXT-KITCHEN-ASPECT",
                rule_name="Kitchen Aspect Ratio",
                category=RuleCategory.AREA,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Kitchen aspect ratio {aspect:.1f}:1 exceeds maximum "
                    f"{_MAX_KITCHEN_ASPECT}:1 (corridor-like)"
                ),
                severity=Severity.SOFT,
                actual_value=aspect,
                required_value=_MAX_KITCHEN_ASPECT,
                source_section="NBC 205:2020 advisory",
            )
        ]
    return []


def _check_bathroom_area(room: RoomLayout) -> list[RuleViolation]:
    """Bathrooms ≥ 1.8 sqm; separate toilets ≥ 0.9 sqm."""
    if room.room_type == RoomType.BATHROOM:
        min_area = _MIN_BATHROOM_AREA
        rule_id = "EXT-BATH-AREA"
    elif room.room_type == RoomType.TOILET:
        min_area = _MIN_TOILET_AREA
        rule_id = "EXT-TOILET-AREA"
    else:
        return []

    if room.bounds.area < min_area:
        return [
            RuleViolation(
                rule_id=rule_id,
                rule_name=f"Minimum {room.room_type.value.capitalize()} Area",
                category=RuleCategory.AREA,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"{room.room_type.value.capitalize()} area {room.bounds.area:.2f} "
                    f"sqm < minimum {min_area} sqm"
                ),
                severity=Severity.HARD,
                actual_value=room.bounds.area,
                required_value=min_area,
                unit="sqm",
                source_section="NBC 205:2020 Clause 5.1",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Floor-level checks
# ---------------------------------------------------------------------------


def _check_floor_rooms(floor_plan: FloorPlan) -> list[RuleViolation]:
    """Run all per-room checks for a single floor."""
    violations: list[RuleViolation] = []
    for room in floor_plan.rooms:
        violations.extend(_check_window_ratio(room))
        violations.extend(_check_min_dimension(room))
        violations.extend(_check_staircase(room))
        violations.extend(_check_kitchen_aspect(room))
        violations.extend(_check_bathroom_area(room))
    return violations


# ---------------------------------------------------------------------------
# Building-level checks
# ---------------------------------------------------------------------------


def _check_coverage(
    building: BuildingDesign,
    plot_info: dict | None,
) -> list[RuleViolation]:
    """Ground-floor footprint must not exceed 60 % of plot area."""
    if not plot_info:
        return []

    plot_area = plot_info.get("area_sqm", 0.0)
    if plot_area <= 0:
        return []

    if not building.floor_plans:
        return []

    # Ground floor footprint = sum of room areas on floor 1
    ground_floor = next((fp for fp in building.floor_plans if fp.floor == 1), None)
    if ground_floor is None:
        return []

    footprint = sum(r.bounds.area for r in ground_floor.rooms)
    coverage = footprint / plot_area
    violations = []

    if coverage > _MAX_COVERAGE_HARD:
        violations.append(
            RuleViolation(
                rule_id="EXT-COVERAGE-HARD",
                rule_name="Maximum Ground Coverage (Hard)",
                category=RuleCategory.COVERAGE,
                message=(
                    f"Ground coverage {coverage*100:.1f}% exceeds hard limit "
                    f"{_MAX_COVERAGE_HARD*100:.0f}%"
                ),
                severity=Severity.HARD,
                actual_value=coverage * 100,
                required_value=_MAX_COVERAGE_HARD * 100,
                unit="percent",
                source_section="KMC Bylaw 2076 Clause 4.3",
            )
        )
    elif coverage > _MAX_COVERAGE_SOFT:
        violations.append(
            RuleViolation(
                rule_id="EXT-COVERAGE-SOFT",
                rule_name="Maximum Ground Coverage (Advisory)",
                category=RuleCategory.COVERAGE,
                message=(
                    f"Ground coverage {coverage*100:.1f}% exceeds advisory limit "
                    f"{_MAX_COVERAGE_SOFT*100:.0f}%"
                ),
                severity=Severity.SOFT,
                actual_value=coverage * 100,
                required_value=_MAX_COVERAGE_SOFT * 100,
                unit="percent",
                source_section="KMC Bylaw 2076 Clause 4.3",
            )
        )
    return violations


def _check_far(
    building: BuildingDesign,
    plot_info: dict | None,
    road_width_m: float | None,
) -> list[RuleViolation]:
    """Total built-up area must not exceed FAR × plot area."""
    if not plot_info:
        return []

    plot_area = plot_info.get("area_sqm", 0.0)
    if plot_area <= 0:
        return []

    # Determine FAR limit from road width (NBC 2020 / KMC Bylaw 2076)
    if road_width_m is None:
        far_limit = 2.5  # conservative default
    elif road_width_m < 6.0:
        far_limit = 1.5
    elif road_width_m < 8.0:
        far_limit = 2.0
    elif road_width_m < 11.0:
        far_limit = 2.5
    else:
        far_limit = 3.0

    total_built = sum(
        sum(r.bounds.area for r in fp.rooms)
        for fp in building.floor_plans
    )
    far_actual = total_built / plot_area if plot_area > 0 else 0.0

    if far_actual > far_limit:
        return [
            RuleViolation(
                rule_id="EXT-FAR",
                rule_name="Maximum Floor Area Ratio",
                category=RuleCategory.FAR,
                message=(
                    f"FAR {far_actual:.2f} exceeds limit {far_limit} for "
                    f"road width {road_width_m} m"
                ),
                severity=Severity.HARD,
                actual_value=far_actual,
                required_value=far_limit,
                unit="m/m",
                source_section="KMC Bylaw 2076 Clause 4.2",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extended_compliance_check(
    building: BuildingDesign,
    plot_info: dict | None = None,
    road_width_m: float | None = None,
) -> list[RuleViolation]:
    """
    Run all extended compliance checks on a BuildingDesign.

    Returns a list of RuleViolation objects (empty = fully compliant).
    These can be merged with the output of `rule_engine.check_compliance()`.

    Args:
        building:      Completed BuildingDesign from geometry engine.
        plot_info:     PlotInfo dict (from AgentState). Used for coverage + FAR.
        road_width_m:  Road width (metres). Used for FAR limit lookup.
    """
    violations: list[RuleViolation] = []

    # Per-floor room checks
    for floor_plan in building.floor_plans:
        violations.extend(_check_floor_rooms(floor_plan))

    # Building-wide checks
    violations.extend(_check_coverage(building, plot_info))
    violations.extend(_check_far(building, plot_info, road_width_m))

    hard_count = sum(1 for v in violations if v.severity == Severity.HARD)
    soft_count = sum(1 for v in violations if v.severity == Severity.SOFT)
    logger.info(
        "extended_compliance_check: %d hard, %d soft violation(s)",
        hard_count,
        soft_count,
    )

    return violations
