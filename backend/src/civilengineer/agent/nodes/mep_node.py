"""
mep_node — MEP routing node (between geometry and human_review).

Runs the MEP router over all floor plans and attaches MEPNetwork
to each FloorPlan in state["floor_plans"].
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from civilengineer.agent.state import AgentState
from civilengineer.reasoning_engine.mep_router import (
    attach_mep_to_floor_plans,
    build_mep_network,
)
from civilengineer.schemas.design import DesignRequirements, FloorPlan
from civilengineer.schemas.mep import MEPRequirements

logger = logging.getLogger(__name__)


def mep_routing_node(state: AgentState) -> dict:
    """
    Run MEP routing over all floor plans.

    Reads:   state["floor_plans"], state["requirements"]
    Writes:  state["floor_plans"] (with mep_network attached per floor)
    Appends: decision_event of type "mep_routing"
    """
    floor_plan_dicts = state.get("floor_plans")
    req_dict         = state.get("requirements")
    errors           = list(state.get("errors", []))
    warnings         = list(state.get("warnings", []))

    if not floor_plan_dicts:
        errors.append("mep_routing_node: no floor_plans in state.")
        return {"errors": errors}

    try:
        floor_plans: list[FloorPlan] = [
            FloorPlan.model_validate(d) for d in floor_plan_dicts
        ]

        # Extract MEP requirements if available
        mep_req: MEPRequirements | None = None
        if req_dict:
            req = DesignRequirements.model_validate(req_dict)
            if req.mep_requirements:
                mep_req = req.mep_requirements

        # Build full MEP network
        network = build_mep_network(floor_plans, mep_req)

        # Attach per-floor sub-networks
        attach_mep_to_floor_plans(floor_plans, network)

        total_runs   = len(network.conduit_runs)
        total_stacks = len(network.plumbing_stacks)
        total_panels = len(network.panels)
        total_load   = network.total_electrical_load_kva
        total_pipe   = network.total_pipe_run_m

        logger.info(
            "mep_routing_node: %d conduit runs, %d plumbing stacks, "
            "%d panels, %.1f kVA total load, %.1f m pipe run",
            total_runs, total_stacks, total_panels, total_load, total_pipe,
        )

        event = {
            "node": "mep_routing",
            "type": "mep_routing",
            "iteration": state.get("revision_count", 0),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "conduit_runs": total_runs,
                "plumbing_stacks": total_stacks,
                "panels": total_panels,
                "total_load_kva": total_load,
                "total_pipe_run_m": total_pipe,
                "phase": network.panels[0].phase if network.panels else "1-phase",
            },
        }

        updated_floor_plan_dicts = [fp.model_dump() for fp in floor_plans]

        return {
            "floor_plans": updated_floor_plan_dicts,
            "errors": errors,
            "warnings": warnings,
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"mep_routing_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}
