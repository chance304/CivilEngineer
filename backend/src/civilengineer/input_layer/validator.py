"""
Input validator.

Cross-checks DesignRequirements against PlotInfo before the solver runs.
Returns a ValidationResult with errors (blockers) and warnings (advisories).

Checks performed:
  1. Plot too small for total requested built-up area
  2. Room count unrealistic for the number of floors
  3. Required rooms present (at least one living room or bedroom + one kitchen)
  4. num_floors within NBC height / FAR envelope
  5. FAR feasibility: requested area vs plot area * FAR limit
  6. Coverage feasibility: ground floor rooms fit within 60% coverage
"""

from __future__ import annotations

from pydantic import BaseModel

from civilengineer.schemas.design import DesignRequirements, RoomRequirement, RoomType
from civilengineer.schemas.project import PlotInfo

# ---------------------------------------------------------------------------
# NBC 2020 NP-KTM approximate limits used for feasibility checks
# ---------------------------------------------------------------------------

# Absolute minimum area targets (sqm) — used to estimate total area requested
_MIN_AREA: dict[RoomType, float] = {
    RoomType.MASTER_BEDROOM: 12.0,
    RoomType.BEDROOM:        9.5,
    RoomType.LIVING_ROOM:    13.5,
    RoomType.DINING_ROOM:    9.0,
    RoomType.KITCHEN:        5.0,
    RoomType.BATHROOM:       2.5,
    RoomType.TOILET:         1.2,
    RoomType.STAIRCASE:      4.5,
    RoomType.CORRIDOR:       3.0,
    RoomType.STORE:          2.0,
    RoomType.POOJA_ROOM:     3.0,
    RoomType.GARAGE:         15.0,
    RoomType.HOME_OFFICE:    7.5,
    RoomType.BALCONY:        2.0,
    RoomType.TERRACE:        6.0,
    RoomType.OTHER:          4.0,
}

# Max FAR for KTM (conservative — actual value is road-width dependent)
_MAX_FAR_CONSERVATIVE = 1.5
_MAX_FAR_GENEROUS = 3.0

# Max ground coverage (%)
_MAX_COVERAGE_PCT = 60.0

# Rooms that require a living or sleeping space to pair with
_HABITABLE_TYPES = frozenset({
    RoomType.MASTER_BEDROOM,
    RoomType.BEDROOM,
    RoomType.LIVING_ROOM,
})


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str]    # blockers — solver will not run
    warnings: list[str]  # advisories — solver continues with warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_requirements(
    requirements: DesignRequirements,
    plot_info: PlotInfo,
    road_width_m: float | None = None,
) -> ValidationResult:
    """
    Validate DesignRequirements against PlotInfo.

    Args:
        requirements : from the requirements interview
        plot_info    : extracted from the uploaded DXF
        road_width_m : front-road width (from ProjectProperties); used for
                       FAR limit selection. If None, conservative FAR used.

    Returns:
        ValidationResult with errors (blocking) and warnings (non-blocking).
    """
    errors: list[str] = []
    warnings: list[str] = []

    _check_room_program(requirements.rooms, errors, warnings)
    _check_floor_count(requirements.num_floors, errors, warnings)
    _check_area_feasibility(
        requirements.rooms, requirements.num_floors,
        plot_info, road_width_m, errors, warnings,
    )
    _check_coverage_feasibility(
        requirements.rooms, plot_info, errors, warnings,
    )
    _check_staircase(requirements.rooms, requirements.num_floors, warnings)

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal checks
# ---------------------------------------------------------------------------


def _check_room_program(
    rooms: list[RoomRequirement],
    errors: list[str],
    warnings: list[str],
) -> None:
    if not rooms:
        errors.append("No rooms specified in DesignRequirements.")
        return

    types = [r.room_type for r in rooms]
    has_habitable = any(t in _HABITABLE_TYPES for t in types)
    if not has_habitable:
        errors.append(
            "No habitable room specified. "
            "Add at least one bedroom or living room."
        )

    has_kitchen = RoomType.KITCHEN in types
    if not has_kitchen and len(rooms) > 2:
        warnings.append(
            "No kitchen in room program. "
            "A residential building should include a kitchen."
        )

    bedroom_count = sum(
        1 for t in types
        if t in (RoomType.MASTER_BEDROOM, RoomType.BEDROOM)
    )
    bathroom_count = sum(
        1 for t in types
        if t in (RoomType.BATHROOM, RoomType.TOILET)
    )
    if bedroom_count > 0 and bathroom_count == 0:
        warnings.append(
            f"{bedroom_count} bedroom(s) but no bathroom or toilet specified. "
            "Minimum 1 bathroom recommended."
        )


def _check_floor_count(
    num_floors: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if num_floors < 1:
        errors.append("num_floors must be at least 1.")
    elif num_floors > 4:
        warnings.append(
            f"{num_floors}-storey building requires structural engineering review. "
            "NBC 2020 NBC 105 applies for buildings > 4 storeys in KTM valley."
        )
    if num_floors > 7:
        errors.append(
            f"{num_floors} floors exceeds NBC 2020 residential limit of 7 storeys "
            "without a detailed structural report."
        )


def _check_area_feasibility(
    rooms: list[RoomRequirement],
    num_floors: int,
    plot_info: PlotInfo,
    road_width_m: float | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    # Total minimum built-up area from requested rooms
    total_min_sqm = sum(
        r.min_area if r.min_area else _MIN_AREA.get(r.room_type, 4.0)
        for r in rooms
    )

    # Maximum allowed built-up area from FAR
    far_limit = _MAX_FAR_GENEROUS if (road_width_m and road_width_m >= 8.0) else _MAX_FAR_CONSERVATIVE
    max_allowed_sqm = plot_info.area_sqm * far_limit

    if total_min_sqm > max_allowed_sqm:
        errors.append(
            f"Requested rooms require ≥ {total_min_sqm:.0f} sqm built-up area, "
            f"but FAR {far_limit:.1f} allows only {max_allowed_sqm:.0f} sqm "
            f"on this {plot_info.area_sqm:.0f} sqm plot. "
            "Reduce the number of rooms or request a variance."
        )
    elif total_min_sqm > max_allowed_sqm * 0.85:
        warnings.append(
            f"Requested rooms ({total_min_sqm:.0f} sqm minimum) will use "
            f"{total_min_sqm / max_allowed_sqm * 100:.0f}% of allowed FAR "
            f"({max_allowed_sqm:.0f} sqm). Little margin for circulation space."
        )

    # Each floor can hold at most X sqm (based on max coverage)
    max_ground_floor_sqm = plot_info.area_sqm * (_MAX_COVERAGE_PCT / 100)
    max_total_sqm_coverage = max_ground_floor_sqm * num_floors

    if total_min_sqm > max_total_sqm_coverage * 1.1:
        warnings.append(
            f"Rooms may not fit in {num_floors} floor(s) within 60% coverage limit. "
            f"Consider increasing num_floors or reducing room count."
        )


def _check_coverage_feasibility(
    rooms: list[RoomRequirement],
    plot_info: PlotInfo,
    errors: list[str],
    warnings: list[str],
) -> None:
    # Ground floor rooms (conservative: all rooms on 1 floor)
    total_min_sqm = sum(
        r.min_area if r.min_area else _MIN_AREA.get(r.room_type, 4.0)
        for r in rooms
    )
    max_ground_sqm = plot_info.area_sqm * (_MAX_COVERAGE_PCT / 100)

    if total_min_sqm > max_ground_sqm * 2.0:
        # Flagged only when even spreading over 2 floors doesn't help
        warnings.append(
            f"Total minimum room area ({total_min_sqm:.0f} sqm) is large relative "
            f"to plot size ({plot_info.area_sqm:.0f} sqm). "
            "The solver may need to compress some room dimensions."
        )


def _check_staircase(
    rooms: list[RoomRequirement],
    num_floors: int,
    warnings: list[str],
) -> None:
    types = [r.room_type for r in rooms]
    has_staircase = RoomType.STAIRCASE in types
    if num_floors > 1 and not has_staircase:
        warnings.append(
            f"Building has {num_floors} floor(s) but no staircase in room program. "
            "A staircase will be added automatically."
        )
