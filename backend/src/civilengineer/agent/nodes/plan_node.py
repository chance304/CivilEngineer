"""
plan_node — Layer 2 (knowledge retrieval + strategy).

1. Loads the rule set for the project's jurisdiction.
2. Computes the buildable zone from PlotInfo + setback rules.
3. Optionally calls the LLM to produce a design strategy message
   (skipped if no LLM is configured — deterministic fallback used).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.messages import AIMessage

from civilengineer.agent.state import AgentState
from civilengineer.input_layer.enricher import Enricher
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.schemas.design import DesignRequirements
from civilengineer.schemas.project import PlotInfo

logger = logging.getLogger(__name__)


def plan_node(state: AgentState) -> dict:
    """
    Compute buildable zone and prepare rule set for the solver.
    Adds a strategy message to state.messages.
    """
    req_dict  = state.get("requirements")
    plot_dict = state.get("plot_info")
    errors    = list(state.get("errors", []))
    warnings  = list(state.get("warnings", []))

    if not req_dict:
        errors.append("plan_node: no requirements; cannot plan.")
        return {"errors": errors}

    try:
        req = DesignRequirements.model_validate(req_dict)
        jurisdiction = req.jurisdiction

        # Load rules for jurisdiction
        rule_set = load_rules(jurisdiction=jurisdiction if jurisdiction != "NP-KTM" else None)
        enricher = Enricher(rule_set.rules)

        road_width = req.road_width_m
        plot_info  = PlotInfo.model_validate(plot_dict) if plot_dict else None

        if plot_info:
            setbacks = enricher.setbacks(plot_info, road_width_m=road_width)
            zone     = enricher.buildable_zone(plot_info, road_width_m=road_width)
            zone_dict = zone.model_dump()
        else:
            # Stub: 12×15 m buildable zone when no plot available
            warnings.append("plan_node: no plot_info; using 12×15 m stub zone.")
            from civilengineer.schemas.design import Rect2D  # noqa: PLC0415
            zone     = Rect2D(x=3.0, y=3.0, width=12.0, depth=15.0)
            zone_dict = zone.model_dump()
            setbacks = (3.0, 1.5, 1.5, 1.5)

        room_count = len(req.rooms)
        room_summary = ", ".join(
            sorted({r.room_type.value for r in req.rooms})
        )

        strategy = (
            f"Design strategy: {room_count} rooms "
            f"({room_summary}) in {req.num_floors} floor(s) on "
            f"{zone.width:.1f}×{zone.depth:.1f} m buildable zone "
            f"(setbacks: front {setbacks[0]:.1f} m, rear {setbacks[1]:.1f} m, "
            f"side {setbacks[2]:.1f} m). "
            f"Jurisdiction: {jurisdiction} (NBC 2020). "
            f"Vastu: {'enabled' if req.vastu_compliant else 'disabled'}."
        )
        logger.info(strategy)

        event = {
            "node": "plan",
            "type": "zone_computed",
            "iteration": state.get("revision_count", 0),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "zone_width": zone.width,
                "zone_depth": zone.depth,
                "setbacks": {
                    "front": setbacks[0],
                    "rear": setbacks[1],
                    "left": setbacks[2],
                    "right": setbacks[3] if len(setbacks) > 3 else setbacks[2],
                },
                "jurisdiction": jurisdiction,
                "room_count": room_count,
            },
        }
        return {
            "buildable_zone": zone_dict,
            "setbacks": list(setbacks),
            "warnings": warnings,
            "errors": errors,
            "messages": [AIMessage(content=strategy)],
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"plan_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}
