"""
solve_node — Layer 2 (constraint solver).

Calls constraint_solver.solve_layout() with the buildable zone and rules.
Sets state["solve_result"] and appends any solver warnings to state["warnings"].
"""

from __future__ import annotations

import logging

from civilengineer.agent.state import AgentState
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.reasoning_engine.constraint_solver import SolveStatus, solve_layout
from civilengineer.schemas.design import DesignRequirements, Rect2D

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30.0


def solve_node(state: AgentState) -> dict:
    """Run the CP-SAT constraint solver."""
    req_dict    = state.get("requirements")
    zone_dict   = state.get("buildable_zone")
    errors      = list(state.get("errors", []))
    warnings    = list(state.get("warnings", []))

    if not req_dict:
        errors.append("solve_node: no requirements in state.")
        return {"errors": errors}

    if not zone_dict:
        errors.append("solve_node: no buildable_zone in state — run plan_node first.")
        return {"errors": errors}

    try:
        req   = DesignRequirements.model_validate(req_dict)
        zone  = Rect2D.model_validate(zone_dict)
        rules = load_rules().rules

        result = solve_layout(req, zone, rules, timeout_s=_DEFAULT_TIMEOUT_S)

        warnings.extend(result.warnings)
        logger.info(
            "Solver: status=%s placed=%d unplaced=%d time=%.2fs",
            result.status, len(result.placed_rooms),
            len(result.unplaced_rooms), result.solver_time_s,
        )

        if result.status == SolveStatus.UNSAT:
            errors.append(
                f"Constraint solver returned UNSAT: rooms cannot fit in "
                f"{zone.width:.1f}×{zone.depth:.1f} m buildable zone. "
                "Try relax_node or reduce room count."
            )

        return {
            "solve_result": result.model_dump(),
            "warnings": warnings,
            "errors": errors,
        }

    except Exception as exc:
        msg = f"solve_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}
