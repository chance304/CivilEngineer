"""
Construction cost estimator.

Produces a `CostEstimate` for a `BuildingDesign` using ₹/sqm unit rates
broken down by room type and material grade.

Rates are Nepal market estimates (2024–25) in Indian Rupees (INR).
The same tool is relevant for Indian projects with similar construction methods.

Three material grades:
  basic    — brick + local sand + standard fitting (budget housing)
  standard — AAC blocks + branded finishing (mid-segment)
  premium  — RCC + imported marble + premium fitting (high-end)

Usage
-----
    from civilengineer.output_layer.cost_estimator import CostEstimator
    estimator = CostEstimator(material_grade="standard")
    estimate  = estimator.estimate(building_design)
    print(estimate.total_cost_inr)
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from civilengineer.schemas.design import BuildingDesign, RoomType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate tables  (₹ per sqm of finished floor area)
# ---------------------------------------------------------------------------

MaterialGrade = Literal["basic", "standard", "premium"]

# Base structure rate (₹/sqm) — applies to all rooms equally
_STRUCTURE_RATE: dict[MaterialGrade, float] = {
    "basic":    12_000,
    "standard": 18_000,
    "premium":  28_000,
}

# Additional finishing rate (₹/sqm) — room-type-specific premium over structure
_FINISH_RATE: dict[RoomType, dict[MaterialGrade, float]] = {
    RoomType.MASTER_BEDROOM: {"basic": 2_500, "standard": 4_500, "premium": 9_000},
    RoomType.BEDROOM:        {"basic": 2_000, "standard": 4_000, "premium": 8_000},
    RoomType.LIVING_ROOM:    {"basic": 3_000, "standard": 5_500, "premium":12_000},
    RoomType.DINING_ROOM:    {"basic": 2_500, "standard": 4_500, "premium": 9_000},
    RoomType.KITCHEN:        {"basic": 4_000, "standard": 7_000, "premium":15_000},
    RoomType.BATHROOM:       {"basic": 5_000, "standard": 9_000, "premium":18_000},
    RoomType.TOILET:         {"basic": 4_500, "standard": 8_000, "premium":15_000},
    RoomType.STAIRCASE:      {"basic": 3_000, "standard": 5_000, "premium": 9_000},
    RoomType.CORRIDOR:       {"basic": 1_500, "standard": 2_500, "premium": 5_000},
    RoomType.STORE:          {"basic": 1_000, "standard": 2_000, "premium": 4_000},
    RoomType.POOJA_ROOM:     {"basic": 3_000, "standard": 5_500, "premium":10_000},
    RoomType.GARAGE:         {"basic": 2_000, "standard": 3_500, "premium": 6_000},
    RoomType.HOME_OFFICE:    {"basic": 2_500, "standard": 4_500, "premium": 9_000},
    RoomType.BALCONY:        {"basic": 1_200, "standard": 2_000, "premium": 4_000},
    RoomType.TERRACE:        {"basic":   800, "standard": 1_500, "premium": 3_000},
    RoomType.OTHER:          {"basic": 1_500, "standard": 2_500, "premium": 5_000},
}

# MEP (mechanical, electrical, plumbing) as % of structure cost
_MEP_FACTOR: dict[MaterialGrade, float] = {
    "basic":    0.12,
    "standard": 0.18,
    "premium":  0.25,
}

# Contingency factor
_CONTINGENCY: float = 0.05   # 5 %

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class RoomCost(BaseModel):
    room_id: str
    room_type: str
    floor: int
    area_sqm: float
    structure_cost: float
    finish_cost: float
    total_cost: float


class CostEstimate(BaseModel):
    """Full construction cost estimate for a building design."""

    project_id: str
    design_id: str
    material_grade: str
    total_area_sqm: float
    structure_cost: float       # all rooms: structure rate × area
    finish_cost: float          # all rooms: finishing rate × area
    mep_cost: float             # MEP as fraction of structure
    contingency_cost: float     # 5 % of (structure + finish + MEP)
    total_cost_inr: float       # grand total
    cost_per_sqm_inr: float     # total / total_area_sqm

    room_breakdown: list[RoomCost]

    # Summary by room type (aggregated)
    type_breakdown: dict[str, float]   # room_type → total cost

    def formatted_total(self) -> str:
        crore = self.total_cost_inr / 1_00_00_000
        lakh  = self.total_cost_inr / 1_00_000
        if crore >= 1.0:
            return f"₹ {crore:.2f} Cr  (≈ ₹ {lakh:.1f} L)"
        return f"₹ {lakh:.2f} L"


# ---------------------------------------------------------------------------
# Estimator class
# ---------------------------------------------------------------------------


class CostEstimator:
    """
    Estimate construction cost for a BuildingDesign.

    Args:
        material_grade: One of "basic", "standard", "premium".
    """

    def __init__(self, material_grade: MaterialGrade = "standard") -> None:
        if material_grade not in ("basic", "standard", "premium"):
            raise ValueError(f"Unknown material_grade: {material_grade!r}")
        self.grade: MaterialGrade = material_grade

    def estimate(self, building: BuildingDesign) -> CostEstimate:
        """Run the cost estimate and return a CostEstimate."""
        room_costs: list[RoomCost] = []
        total_structure = 0.0
        total_finish    = 0.0
        type_totals: dict[str, float] = {}

        struct_rate = _STRUCTURE_RATE[self.grade]

        for floor_plan in building.floor_plans:
            for room in floor_plan.rooms:
                area = room.bounds.area
                if area <= 0:
                    continue

                finish_table = _FINISH_RATE.get(room.room_type, _FINISH_RATE[RoomType.OTHER])
                finish_rate  = finish_table[self.grade]

                s_cost = area * struct_rate
                f_cost = area * finish_rate
                room_total = s_cost + f_cost

                total_structure += s_cost
                total_finish    += f_cost

                rt_key = room.room_type.value
                type_totals[rt_key] = type_totals.get(rt_key, 0.0) + room_total

                room_costs.append(
                    RoomCost(
                        room_id=room.room_id,
                        room_type=rt_key,
                        floor=room.floor,
                        area_sqm=round(area, 2),
                        structure_cost=round(s_cost, 0),
                        finish_cost=round(f_cost, 0),
                        total_cost=round(room_total, 0),
                    )
                )

        mep_cost         = total_structure * _MEP_FACTOR[self.grade]
        subtotal         = total_structure + total_finish + mep_cost
        contingency_cost = subtotal * _CONTINGENCY
        grand_total      = subtotal + contingency_cost

        total_area = sum(r.area_sqm for r in room_costs)
        cost_per_sqm = grand_total / total_area if total_area > 0 else 0.0

        logger.info(
            "CostEstimator [%s]: %.0f sqm → ₹ %.0f (%.0f/sqm)",
            self.grade, total_area, grand_total, cost_per_sqm,
        )

        return CostEstimate(
            project_id=building.project_id,
            design_id=building.design_id,
            material_grade=self.grade,
            total_area_sqm=round(total_area, 2),
            structure_cost=round(total_structure, 0),
            finish_cost=round(total_finish, 0),
            mep_cost=round(mep_cost, 0),
            contingency_cost=round(contingency_cost, 0),
            total_cost_inr=round(grand_total, 0),
            cost_per_sqm_inr=round(cost_per_sqm, 0),
            room_breakdown=room_costs,
            type_breakdown={k: round(v, 0) for k, v in type_totals.items()},
        )
