"""
Deterministic rule engine.

Takes a BuildingDesign + site context and checks it against a list of
DesignRule objects, producing a ComplianceReport.

Checked rule types:
  min_area               — room floor area ≥ numeric_value
  min_dimension          — shorter room side ≥ numeric_value
  max_coverage           — ground floor area / plot area ≤ numeric_value %
  max_far                — total built-up area / plot area ≤ numeric_value
  min_setback_front      — building.setback_front ≥ numeric_value
  min_setback_rear       — building.setback_rear ≥ numeric_value
  min_setback_side       — min(left, right) ≥ numeric_value
  min_floor_height       — FloorPlan.floor_height ≥ numeric_value
  min_window_area_ratio  — sum(window area) / room area ≥ numeric_value %
  min_stair_width        — staircase shorter dimension ≥ numeric_value
  vastu_location         — room center in expected quadrant (advisory)

Skipped (data not in FloorPlan schema):
  max_riser_height, min_tread_depth, min_stair_headroom,
  min_main_door_width, min_internal_door_width, kitchen_ventilation, …
  (flagged in report.rules_skipped)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from civilengineer.schemas.design import BuildingDesign, RoomLayout, RoomType
from civilengineer.schemas.rules import (
    ComplianceReport,
    DesignRule,
    RuleCategory,
    RuleViolation,
    Severity,
)

logger = logging.getLogger(__name__)

# Rule types that can be checked from the BuildingDesign schema
_CHECKABLE_RULE_TYPES: frozenset[str] = frozenset({
    "min_area",
    "min_dimension",
    "max_coverage",
    "max_far",
    "min_setback_front",
    "min_setback_rear",
    "min_setback_side",
    "min_floor_height",
    "min_window_area_ratio",
    "min_stair_width",
    "vastu_location",
})

# Vastu quadrant name → (x_is_right, y_is_top) booleans relative to center
_VASTU_QUADRANTS: dict[str, tuple[bool, bool]] = {
    "northeast": (True, True),
    "northwest": (False, True),
    "southeast": (True, False),
    "southwest": (False, False),
    "north":     (None, True),   # type: ignore[assignment]  # top half
    "south":     (None, False),  # type: ignore[assignment]  # bottom half
    "east":      (True, None),   # type: ignore[assignment]  # right half
    "west":      (False, None),  # type: ignore[assignment]  # left half
}

# Preferred vastu quadrants for each room type (rule_id to list of quadrant names)
_VASTU_PREFERRED: dict[str, list[str]] = {
    "master_bedroom": ["southwest"],
    "kitchen":        ["southeast"],
    "pooja_room":     ["northeast"],
    "living_room":    ["north", "northeast"],
    "staircase":      ["south", "southwest"],
    "toilet":         ["south", "southeast"],
    "bathroom":       ["south", "southeast"],
    "garage":         ["southeast", "northwest"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_compliance(
    building: BuildingDesign,
    plot_area_sqm: float,
    rules: list[DesignRule],
    road_width_m: float | None = None,
    vastu_enabled: bool = False,
) -> ComplianceReport:
    """
    Check building against all applicable rules.

    Args:
        building      : fully-populated BuildingDesign
        plot_area_sqm : total plot area in square metres (from PlotInfo)
        rules         : list of DesignRule objects (e.g. from rule_compiler.load_rules())
        road_width_m  : fronting road width; required for setback and FAR rules
        vastu_enabled : if False, vastu rules are skipped entirely

    Returns:
        ComplianceReport
    """
    violations: list[RuleViolation] = []
    warnings:   list[RuleViolation] = []
    advisories: list[RuleViolation] = []
    rules_checked = 0
    rules_skipped = 0

    def _record(v: RuleViolation) -> None:
        if v.severity == Severity.HARD:
            violations.append(v)
        elif v.severity == Severity.SOFT:
            warnings.append(v)
        else:
            advisories.append(v)

    # Flatten rooms across all floors
    all_rooms = [r for fp in building.floor_plans for r in fp.rooms]
    floor1_rooms = [r for r in all_rooms if r.floor == 1]

    # Derived metrics
    ground_floor_sqm = sum(r.area for r in floor1_rooms) if floor1_rooms else 0.0
    total_built_sqm  = sum(r.area for r in all_rooms)    if all_rooms    else 0.0
    coverage_pct = (ground_floor_sqm / plot_area_sqm * 100.0) if plot_area_sqm > 0 else 0.0
    far_actual   = (total_built_sqm  / plot_area_sqm)         if plot_area_sqm > 0 else 0.0

    # Filter rules applicable to this context
    applicable = _filter_rules(rules, road_width_m, plot_area_sqm, building.num_floors, vastu_enabled)

    for rule in applicable:
        if not rule.is_active:
            continue

        rt = rule.rule_type

        if rt not in _CHECKABLE_RULE_TYPES:
            rules_skipped += 1
            continue

        found = _check_rule(
            rule=rule,
            building=building,
            all_rooms=all_rooms,
            floor1_rooms=floor1_rooms,
            coverage_pct=coverage_pct,
            far_actual=far_actual,
        )
        rules_checked += 1
        for v in found:
            _record(v)

    return ComplianceReport(
        design_id=building.design_id,
        project_id=building.project_id,
        jurisdiction=building.jurisdiction,
        checked_at=datetime.now(UTC),
        violations=violations,
        warnings=warnings,
        advisories=advisories,
        compliant=len(violations) == 0,
        rules_checked=rules_checked,
        rules_skipped=rules_skipped,
        coverage_pct=round(coverage_pct, 1),
        far_actual=round(far_actual, 3),
        total_built_sqm=round(total_built_sqm, 2),
    )


# ---------------------------------------------------------------------------
# Rule filtering
# ---------------------------------------------------------------------------


def _filter_rules(
    rules: list[DesignRule],
    road_width: float | None,
    plot_area: float,
    num_floors: int,
    vastu_enabled: bool,
) -> list[DesignRule]:
    out = []
    for rule in rules:
        c = rule.conditions

        # Vastu rules: skip unless vastu is enabled
        if rule.category == RuleCategory.VASTU and not vastu_enabled:
            continue
        if c.get("vastu_only") and not vastu_enabled:
            continue

        # Road-width conditions (skip rule if road_width unavailable)
        has_road_cond = "road_width_min" in c or "road_width_max" in c
        if has_road_cond:
            if road_width is None:
                continue  # can't evaluate this rule without road width
            rw_min = c.get("road_width_min", 0.0)
            rw_max = c.get("road_width_max", None)
            if road_width < rw_min:
                continue
            if rw_max is not None and road_width >= rw_max:
                continue

        # Plot area conditions
        if "plot_area_min" in c and plot_area < c["plot_area_min"]:
            continue
        if "plot_area_max" in c and plot_area >= c["plot_area_max"]:
            continue

        # Floor count conditions
        if "num_floors_min" in c and num_floors < c["num_floors_min"]:
            continue
        if "num_floors_max" in c and num_floors > c["num_floors_max"]:
            continue

        out.append(rule)
    return out


# ---------------------------------------------------------------------------
# Rule dispatch
# ---------------------------------------------------------------------------


def _check_rule(
    rule: DesignRule,
    building: BuildingDesign,
    all_rooms: list[RoomLayout],
    floor1_rooms: list[RoomLayout],
    coverage_pct: float,
    far_actual: float,
) -> list[RuleViolation]:
    rt = rule.rule_type

    if rt == "min_area":
        return _check_min_area(rule, all_rooms)
    if rt == "min_dimension":
        return _check_min_dimension(rule, all_rooms)
    if rt == "max_coverage":
        return _check_max_coverage(rule, coverage_pct)
    if rt == "max_far":
        return _check_max_far(rule, far_actual)
    if rt == "min_setback_front":
        return _check_setback_single(rule, building.setback_front, "front")
    if rt == "min_setback_rear":
        return _check_setback_single(rule, building.setback_rear, "rear")
    if rt == "min_setback_side":
        return _check_setback_side(rule, building)
    if rt == "min_floor_height":
        return _check_floor_height(rule, building)
    if rt == "min_window_area_ratio":
        return _check_window_area(rule, all_rooms)
    if rt == "min_stair_width":
        return _check_stair_width(rule, all_rooms)
    if rt == "vastu_location":
        return _check_vastu_location(rule, all_rooms, building)

    return []


# ---------------------------------------------------------------------------
# Individual checkers
# ---------------------------------------------------------------------------


def _check_min_area(rule: DesignRule, rooms: list[RoomLayout]) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    out = []
    for room in rooms:
        if not _room_matches(room, rule.applies_to):
            continue
        if room.area < rule.numeric_value - 1e-6:
            out.append(RuleViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"{room.name} area {room.area:.2f} sqm is below minimum "
                    f"{rule.numeric_value} sqm."
                ),
                actual_value=round(room.area, 2),
                required_value=rule.numeric_value,
                unit=rule.unit,
                source_section=rule.source_section,
            ))
    return out


def _check_min_dimension(rule: DesignRule, rooms: list[RoomLayout]) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    out = []
    for room in rooms:
        if not _room_matches(room, rule.applies_to):
            continue
        shorter = min(room.bounds.width, room.bounds.depth)
        if shorter < rule.numeric_value - 1e-6:
            out.append(RuleViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"{room.name} shorter dimension {shorter:.2f} m is below "
                    f"minimum {rule.numeric_value} m."
                ),
                actual_value=round(shorter, 3),
                required_value=rule.numeric_value,
                unit=rule.unit,
                source_section=rule.source_section,
            ))
    return out


def _check_max_coverage(rule: DesignRule, coverage_pct: float) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    if coverage_pct > rule.numeric_value + 1e-6:
        return [RuleViolation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            message=(
                f"Ground coverage {coverage_pct:.1f}% exceeds maximum "
                f"{rule.numeric_value:.0f}%."
            ),
            actual_value=round(coverage_pct, 1),
            required_value=rule.numeric_value,
            unit=rule.unit,
            source_section=rule.source_section,
        )]
    return []


def _check_max_far(rule: DesignRule, far_actual: float) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    if far_actual > rule.numeric_value + 1e-6:
        return [RuleViolation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            message=(
                f"Floor Area Ratio {far_actual:.2f} exceeds maximum "
                f"{rule.numeric_value}."
            ),
            actual_value=round(far_actual, 3),
            required_value=rule.numeric_value,
            unit=rule.unit,
            source_section=rule.source_section,
        )]
    return []


def _check_setback_single(
    rule: DesignRule,
    applied_setback: float,
    side: str,
) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    if applied_setback < rule.numeric_value - 1e-6:
        return [RuleViolation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            message=(
                f"{side.capitalize()} setback {applied_setback:.2f} m is below "
                f"required {rule.numeric_value} m."
            ),
            actual_value=round(applied_setback, 3),
            required_value=rule.numeric_value,
            unit=rule.unit,
            source_section=rule.source_section,
        )]
    return []


def _check_setback_side(rule: DesignRule, building: BuildingDesign) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    min_side = min(building.setback_left, building.setback_right)
    if min_side < rule.numeric_value - 1e-6:
        return [RuleViolation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            message=(
                f"Side setback {min_side:.2f} m (left={building.setback_left:.2f}, "
                f"right={building.setback_right:.2f}) is below required "
                f"{rule.numeric_value} m."
            ),
            actual_value=round(min_side, 3),
            required_value=rule.numeric_value,
            unit=rule.unit,
            source_section=rule.source_section,
        )]
    return []


def _check_floor_height(rule: DesignRule, building: BuildingDesign) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    out = []
    for fp in building.floor_plans:
        # Check rooms that match applies_to
        for room in fp.rooms:
            if not _room_matches(room, rule.applies_to):
                continue
            if fp.floor_height < rule.numeric_value - 1e-6:
                out.append(RuleViolation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    category=rule.category,
                    room_id=room.room_id,
                    room_type=room.room_type.value,
                    message=(
                        f"Floor {fp.floor} height {fp.floor_height:.2f} m is below "
                        f"minimum {rule.numeric_value} m for {room.room_type.value}."
                    ),
                    actual_value=round(fp.floor_height, 2),
                    required_value=rule.numeric_value,
                    unit=rule.unit,
                    source_section=rule.source_section,
                ))
        break  # Check only once per floor (height is per FloorPlan)
    return out


def _check_window_area(rule: DesignRule, rooms: list[RoomLayout]) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    out = []
    for room in rooms:
        if not _room_matches(room, rule.applies_to):
            continue
        if not room.windows:
            # No windows defined at all — skip (we can't verify without window data)
            continue
        window_area = sum(w.width * w.height for w in room.windows)
        required = room.area * rule.numeric_value / 100.0
        if window_area < required - 1e-6:
            out.append(RuleViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"{room.name} window area {window_area:.2f} sqm is below "
                    f"{rule.numeric_value:.0f}% of room area "
                    f"({required:.2f} sqm required)."
                ),
                actual_value=round(window_area, 2),
                required_value=round(required, 2),
                unit="sqm",
                source_section=rule.source_section,
            ))
    return out


def _check_stair_width(rule: DesignRule, rooms: list[RoomLayout]) -> list[RuleViolation]:
    if rule.numeric_value is None:
        return []
    out = []
    for room in rooms:
        if room.room_type != RoomType.STAIRCASE:
            continue
        shorter = min(room.bounds.width, room.bounds.depth)
        if shorter < rule.numeric_value - 1e-6:
            out.append(RuleViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                category=rule.category,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Staircase clear width {shorter:.2f} m is below "
                    f"minimum {rule.numeric_value} m."
                ),
                actual_value=round(shorter, 3),
                required_value=rule.numeric_value,
                unit=rule.unit,
                source_section=rule.source_section,
            ))
    return out


def _check_vastu_location(
    rule: DesignRule,
    rooms: list[RoomLayout],
    building: BuildingDesign,
) -> list[RuleViolation]:
    """Advisory vastu check — room center should be in expected quadrant."""
    out = []
    cx = building.plot_width / 2.0
    cy = building.plot_depth / 2.0

    preferred_quadrants = [
        tag for tag in rule.tags
        if tag in _VASTU_QUADRANTS
    ]
    if not preferred_quadrants:
        # Extract from rule name / description as fallback
        for q in _VASTU_QUADRANTS:
            if q in rule.name.lower() or q in rule.description.lower():
                preferred_quadrants.append(q)

    if not preferred_quadrants:
        return []

    for room in rooms:
        if not _room_matches(room, rule.applies_to):
            continue
        rx = room.bounds.x + room.bounds.width / 2.0
        ry = room.bounds.y + room.bounds.depth / 2.0
        is_right = rx >= cx
        is_top   = ry >= cy

        in_preferred = False
        for q in preferred_quadrants:
            qr, qt = _VASTU_QUADRANTS[q]
            if qr is None and qt is None:
                in_preferred = True
            elif qr is None:
                in_preferred = (is_top == qt)
            elif qt is None:
                in_preferred = (is_right == qr)
            else:
                in_preferred = (is_right == qr and is_top == qt)
            if in_preferred:
                break

        if not in_preferred:
            actual_q = (
                ("north" if is_top else "south") +
                ("east"  if is_right else "west")
            )
            out.append(RuleViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=Severity.ADVISORY,
                category=rule.category,
                room_id=room.room_id,
                room_type=room.room_type.value,
                message=(
                    f"Vastu: {room.name} is in the {actual_q} quadrant. "
                    f"Preferred: {' or '.join(preferred_quadrants)}."
                ),
                source_section=rule.source_section,
            ))
    return out


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _room_matches(room: RoomLayout, applies_to: list[str]) -> bool:
    if "all" in applies_to:
        return True
    return room.room_type.value in applies_to
