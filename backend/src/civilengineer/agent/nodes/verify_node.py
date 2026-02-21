"""
verify_node — Layer 6 (compliance verification).

Runs the deterministic rule engine over the BuildingDesign and produces
a ComplianceReport. If hard violations are found and revision_count is
below the limit, sets state["should_revise"] = True to trigger the
revise loop.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from civilengineer.agent.state import AgentState
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.reasoning_engine.rule_engine import check_compliance
from civilengineer.schemas.design import BuildingDesign, DesignRequirements

logger = logging.getLogger(__name__)

_MAX_REVISE = 2  # maximum compliance-driven revision cycles


def verify_node(state: AgentState) -> dict:
    """Run rule engine and decide whether to revise or finish."""
    building_dict  = state.get("building_design")
    plot_dict      = state.get("plot_info")
    req_dict       = state.get("requirements")
    revision_count = state.get("revision_count", 0)
    errors         = list(state.get("errors", []))
    warnings       = list(state.get("warnings", []))

    if not building_dict:
        errors.append("verify_node: no building_design in state.")
        return {"errors": errors}

    try:
        building = BuildingDesign.model_validate(building_dict)
        req      = DesignRequirements.model_validate(req_dict) if req_dict else None

        plot_area = 0.0
        road_width = None
        if plot_dict:
            plot_area  = float(plot_dict.get("area_sqm", 0))
        if req:
            road_width = req.road_width_m

        rules    = load_rules().rules
        report   = check_compliance(
            building,
            plot_area_sqm=plot_area,
            rules=rules,
            road_width_m=road_width,
            vastu_enabled=req.vastu_compliant if req else False,
        )

        hard_count = len(report.violations)
        soft_count = len(report.warnings)
        adv_count  = len(report.advisories)

        status_msg = (
            f"Compliance check: {'✓ PASS' if report.compliant else '✗ FAIL'}  |  "
            f"Hard violations: {hard_count}  |  "
            f"Soft warnings: {soft_count}  |  "
            f"Advisories: {adv_count}"
        )
        if report.coverage_pct is not None:
            status_msg += f"  |  Coverage: {report.coverage_pct:.1f}%"

        logger.info(status_msg)

        should_revise = False
        if not report.compliant and revision_count < _MAX_REVISE:
            should_revise = True
            violation_summary = "; ".join(v.message for v in report.violations[:3])
            warnings.append(
                f"Compliance violations found (attempt {revision_count + 1}/"
                f"{_MAX_REVISE}): {violation_summary}"
            )

        return {
            "compliance_report": report.model_dump(),
            "should_revise": should_revise,
            "warnings": warnings,
            "errors": errors,
            "messages": [AIMessage(content=status_msg)],
        }

    except Exception as exc:
        msg = f"verify_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors, "should_revise": False}
