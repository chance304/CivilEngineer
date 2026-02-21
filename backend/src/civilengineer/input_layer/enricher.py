"""
Input enricher.

Computes the buildable zone (zone within the plot after applying code
setbacks) and derived site parameters from PlotInfo + rules.

Usage:
    enricher = Enricher(rules)
    zone = enricher.buildable_zone(plot_info, road_width_m=7.0)
    setbacks = enricher.setbacks(plot_info, road_width_m=7.0)
"""

from __future__ import annotations

import logging

from civilengineer.schemas.design import Rect2D
from civilengineer.schemas.project import PlotInfo
from civilengineer.schemas.rules import DesignRule, RuleCategory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NBC 2020 NP-KTM hard-coded fallbacks (used when no matching rule found)
# ---------------------------------------------------------------------------
_FALLBACK_FRONT  = 3.0   # metres
_FALLBACK_REAR   = 1.5
_FALLBACK_SIDE   = 1.5   # each side


class Enricher:
    """
    Computes site-derived parameters from PlotInfo and building-code rules.

    Args:
        rules : active DesignRule list from rule_compiler.load_rules()
    """

    def __init__(self, rules: list[DesignRule]) -> None:
        self._setback_rules = [
            r for r in rules
            if r.category == RuleCategory.SETBACK and r.is_active
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setbacks(
        self,
        plot_info: PlotInfo,
        road_width_m: float | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Compute (front, rear, left, right) setbacks in metres.

        The front setback is road-width-dependent per NBC 2020.
        Rear and side setbacks may depend on plot area.
        """
        front  = self._front_setback(road_width_m)
        rear   = self._rear_setback(plot_info.area_sqm)
        side_l = self._side_setback(plot_info.area_sqm)
        side_r = side_l  # symmetric for rectangular plots

        logger.debug(
            "Setbacks: front=%.1f rear=%.1f side=%.1f (road_width=%s)",
            front, rear, side_l, road_width_m,
        )
        return front, rear, side_l, side_r

    def buildable_zone(
        self,
        plot_info: PlotInfo,
        road_width_m: float | None = None,
    ) -> Rect2D:
        """
        Return the Rect2D of the buildable area within the plot.

        Coordinate origin: lower-left corner of the plot.
        front setback  → reduces plot depth from the south (y=0 side)
        rear setback   → reduces plot depth from the north (y=depth side)
        left/right     → reduces plot width
        """
        front, rear, left, right = self.setbacks(plot_info, road_width_m)

        zone_x     = left
        zone_y     = front                      # front road = south; y=0 is front
        zone_width = plot_info.width_m - left - right
        zone_depth = plot_info.depth_m - front - rear

        if zone_width <= 0 or zone_depth <= 0:
            logger.warning(
                "Setbacks exceed plot dimensions! "
                "plot=%.1f×%.1f setbacks=(f=%.1f r=%.1f l=%.1f ri=%.1f). "
                "Clamping to 1×1 m.",
                plot_info.width_m, plot_info.depth_m,
                front, rear, left, right,
            )
            zone_width = max(zone_width, 1.0)
            zone_depth = max(zone_depth, 1.0)

        return Rect2D(x=zone_x, y=zone_y, width=zone_width, depth=zone_depth)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _front_setback(self, road_width_m: float | None) -> float:
        """
        NBC 2020 KTM: front setback depends on road width.

        Road < 6 m  → 3.0 m setback
        Road 6–8 m  → 4.5 m setback
        Road > 8 m  → 6.0 m setback
        """
        if road_width_m is None:
            return _FALLBACK_FRONT

        # Find the most specific matching front-setback rule
        best: tuple[float, float] | None = None  # (road_max, setback_value)
        for rule in self._setback_rules:
            if rule.rule_type != "min_setback_front":
                continue
            if rule.numeric_value is None:
                continue
            cond = rule.conditions
            road_min = cond.get("road_width_min", 0.0)
            road_max = cond.get("road_width_max", 999.0)
            if road_min <= road_width_m <= road_max:
                # Pick the rule with the narrowest applicable road range
                span = road_max - road_min
                if best is None or span < best[0]:
                    best = (span, rule.numeric_value)

        if best is not None:
            return best[1]

        # Fallback: linear interpolation
        if road_width_m < 6.0:
            return 3.0
        if road_width_m <= 8.0:
            return 4.5
        return 6.0

    def _rear_setback(self, plot_area_sqm: float) -> float:
        """Find applicable rear-setback rule or use fallback."""
        for rule in self._setback_rules:
            if rule.rule_type != "min_setback_rear":
                continue
            if rule.numeric_value is None:
                continue
            cond = rule.conditions
            area_min = cond.get("plot_area_min", 0.0)
            area_max = cond.get("plot_area_max", 999999.0)
            if area_min <= plot_area_sqm <= area_max:
                return rule.numeric_value

        # Check any unconditional rear-setback rule
        for rule in self._setback_rules:
            if rule.rule_type == "min_setback_rear" and not rule.conditions:
                if rule.numeric_value is not None:
                    return rule.numeric_value

        return _FALLBACK_REAR

    def _side_setback(self, plot_area_sqm: float) -> float:
        """Find applicable side-setback rule or use fallback."""
        for rule in self._setback_rules:
            if rule.rule_type != "min_setback_side":
                continue
            if rule.numeric_value is None:
                continue
            cond = rule.conditions
            area_min = cond.get("plot_area_min", 0.0)
            area_max = cond.get("plot_area_max", 999999.0)
            if area_min <= plot_area_sqm <= area_max:
                return rule.numeric_value

        # Unconditional side rule
        for rule in self._setback_rules:
            if rule.rule_type == "min_setback_side" and not rule.conditions:
                if rule.numeric_value is not None:
                    return rule.numeric_value

        return _FALLBACK_SIDE
