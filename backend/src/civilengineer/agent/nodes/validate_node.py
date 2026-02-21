"""
validate_node — Layer 1.

Cross-validates DesignRequirements against PlotInfo using the
input_layer.validator. Adds errors/warnings to state.
If validation fails with hard errors, sets state["errors"] so the
graph can route to END or a human-review interrupt.
"""

from __future__ import annotations

import logging

from civilengineer.agent.state import AgentState
from civilengineer.input_layer.validator import validate_requirements
from civilengineer.schemas.design import DesignRequirements
from civilengineer.schemas.project import PlotInfo

logger = logging.getLogger(__name__)


def validate_node(state: AgentState) -> dict:
    """Validate requirements against plot constraints."""
    req_dict    = state.get("requirements")
    plot_dict   = state.get("plot_info")
    errors      = list(state.get("errors", []))
    warnings    = list(state.get("warnings", []))

    if not req_dict:
        errors.append("validate_node: no requirements in state; cannot validate.")
        return {"errors": errors, "validation_errors": errors, "validation_warnings": []}

    if not plot_dict:
        warnings.append("validate_node: no plot_info in state; skipping plot-based checks.")
        return {"warnings": warnings, "validation_errors": [], "validation_warnings": warnings}

    try:
        req       = DesignRequirements.model_validate(req_dict)
        plot_info = PlotInfo.model_validate(plot_dict)
        road_width = req.road_width_m

        result = validate_requirements(req, plot_info, road_width_m=road_width)

        logger.info(
            "Validation: valid=%s errors=%d warnings=%d",
            result.is_valid, len(result.errors), len(result.warnings),
        )

        return {
            "validation_errors":   result.errors,
            "validation_warnings": result.warnings,
            "errors":  errors + result.errors,
            "warnings": warnings + result.warnings,
        }
    except Exception as exc:
        msg = f"validate_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors, "validation_errors": [msg], "validation_warnings": []}
