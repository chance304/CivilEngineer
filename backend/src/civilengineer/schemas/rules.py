"""
Building-code rule schemas.

DesignRule    — a single code requirement (area, setback, FAR, …)
RuleSet       — all active rules for a jurisdiction
ComplianceReport — output of the rule engine after checking a BuildingDesign
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RuleCategory(StrEnum):
    AREA        = "area"           # Minimum room areas
    SETBACK     = "setback"        # Setback from plot boundary
    COVERAGE    = "coverage"       # Ground coverage limit
    FAR         = "far"            # Floor Area Ratio
    HEIGHT      = "height"         # Floor-to-ceiling / building height
    OPENING     = "opening"        # Windows and doors
    STAIRCASE   = "staircase"      # Stair geometry
    ADJACENCY   = "adjacency"      # Room proximity requirements
    VENTILATION = "ventilation"    # Natural ventilation
    STRUCTURAL  = "structural"     # Column / beam sizes
    VASTU       = "vastu"          # Vastu Shastra placement (advisory)
    ACCESSIBILITY = "accessibility" # Universal design


class Severity(StrEnum):
    HARD     = "hard"      # Must comply — solver will enforce
    SOFT     = "soft"      # Should comply — relaxable under constraint
    ADVISORY = "advisory"  # Best practice — informational only


# ---------------------------------------------------------------------------
# Core rule model
# ---------------------------------------------------------------------------


class DesignRule(BaseModel):
    """A single building-code rule, loaded from rules.json."""

    rule_id: str                         # e.g. "NP_KTM_AREA_101"
    jurisdiction: str                    # "NP-KTM"
    code_version: str                    # "NBC_2020"
    category: RuleCategory
    severity: Severity
    rule_type: str                       # "min_area", "max_coverage", "min_setback_front", …
    name: str
    description: str
    source_section: str                  # "NBC 205: 2020, Clause 5.1.2"
    applies_to: list[str] = Field(default_factory=list)   # room types or ["all"]
    numeric_value: float | None = None
    unit: str | None = None           # "sqm", "m", "percent", "m/m"
    reference_rooms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    embedding_text: str = ""             # Used for ChromaDB vector indexing
    is_active: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    # Condition keys: road_width_min/max, plot_area_min/max,
    #                 num_floors_min/max, vastu_only


class RuleSet(BaseModel):
    """All active rules for a jurisdiction, loaded from the knowledge base."""

    jurisdiction: str
    code_version: str
    rules: list[DesignRule]
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def by_category(self, category: RuleCategory) -> list[DesignRule]:
        return [r for r in self.rules if r.category == category and r.is_active]

    def by_type(self, rule_type: str) -> list[DesignRule]:
        return [r for r in self.rules if r.rule_type == rule_type and r.is_active]


# ---------------------------------------------------------------------------
# Compliance report
# ---------------------------------------------------------------------------


class RuleViolation(BaseModel):
    rule_id: str
    rule_name: str
    severity: Severity
    category: RuleCategory
    room_id: str | None = None
    room_type: str | None = None
    message: str
    actual_value: float | None = None
    required_value: float | None = None
    unit: str | None = None
    source_section: str = ""


class ComplianceReport(BaseModel):
    """Output of the rule engine after checking a BuildingDesign."""

    design_id: str
    project_id: str
    jurisdiction: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Categorised violations
    violations: list[RuleViolation] = Field(default_factory=list)   # HARD
    warnings: list[RuleViolation] = Field(default_factory=list)     # SOFT
    advisories: list[RuleViolation] = Field(default_factory=list)   # ADVISORY

    # Summary
    compliant: bool = True           # True only if zero HARD violations
    rules_checked: int = 0
    rules_skipped: int = 0           # Skipped due to missing context data

    # Computed metrics
    coverage_pct: float | None = None    # Ground coverage %
    far_actual: float | None = None      # Floor Area Ratio
    total_built_sqm: float | None = None

    def summary(self) -> str:
        parts = [
            f"Compliant: {self.compliant}",
            f"Hard violations: {len(self.violations)}",
            f"Soft warnings: {len(self.warnings)}",
            f"Advisories: {len(self.advisories)}",
        ]
        if self.coverage_pct is not None:
            parts.append(f"Coverage: {self.coverage_pct:.1f}%")
        if self.far_actual is not None:
            parts.append(f"FAR: {self.far_actual:.2f}")
        return "  |  ".join(parts)
