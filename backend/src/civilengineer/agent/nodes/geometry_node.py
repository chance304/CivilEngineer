"""
geometry_node — Layer 3.

Converts SolveResult → FloorPlan list (with room coords, walls,
doors, windows) using the geometry engine.
Also assembles a BuildingDesign for the draw and verify nodes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from civilengineer.agent.state import AgentState
from civilengineer.geometry_engine.layout_generator import generate_floor_plans
from civilengineer.geometry_engine.wall_builder import build_walls, build_walls_cross_floor
from civilengineer.reasoning_engine.constraint_solver import SolveResult
from civilengineer.schemas.design import (
    BuildingDesign,
    ColumnPosition,
    DesignRequirements,
    Rect2D,
)
from civilengineer.schemas.project import PlotInfo

logger = logging.getLogger(__name__)


def geometry_node(state: AgentState) -> dict:
    """Generate FloorPlan list and BuildingDesign from SolveResult."""
    solve_dict  = state.get("solve_result")
    req_dict    = state.get("requirements")
    plot_dict   = state.get("plot_info")
    setbacks    = state.get("setbacks") or [3.0, 1.5, 1.5, 1.5]
    errors      = list(state.get("errors", []))
    warnings    = list(state.get("warnings", []))

    if not solve_dict:
        errors.append("geometry_node: no solve_result in state.")
        return {"errors": errors}

    if not req_dict:
        errors.append("geometry_node: no requirements in state.")
        return {"errors": errors}

    try:
        solve_result = SolveResult.model_validate(solve_dict)
        req          = DesignRequirements.model_validate(req_dict)

        plot_info = None
        if plot_dict:
            plot_info = PlotInfo.model_validate(plot_dict)
        else:
            # Stub PlotInfo for tests / no-plot runs
            from civilengineer.schemas.project import PlotFacing  # noqa: PLC0415
            zone = Rect2D.model_validate(solve_result.buildable_zone.model_dump())
            plot_info = PlotInfo(
                dwg_storage_key="",
                polygon=[],
                area_sqm=(zone.width + float(setbacks[2]) + float(setbacks[3]))
                         * (zone.depth + float(setbacks[0]) + float(setbacks[1])),
                width_m=zone.width + float(setbacks[2]) + float(setbacks[3]),
                depth_m=zone.depth + float(setbacks[0]) + float(setbacks[1]),
                is_rectangular=True,
                north_direction_deg=0.0,
                facing=PlotFacing.SOUTH,
                scale_factor=1.0,
                extraction_confidence=1.0,
            )

        setback_tuple = (
            float(setbacks[0]),
            float(setbacks[1]),
            float(setbacks[2]),
            float(setbacks[3]) if len(setbacks) > 3 else float(setbacks[2]),
        )

        floor_plans = generate_floor_plans(
            solve_result, req, plot_info, setback_tuple
        )

        for i, fp in enumerate(floor_plans):
            build_walls(fp)
            # Cross-floor load-bearing detection: check if walls support upper floor
            upper_fp = floor_plans[i + 1] if i + 1 < len(floor_plans) else None
            build_walls_cross_floor(fp, upper_fp)

        # Wire structural column positions from SolveResult → FloorPlan.columns
        for fp in floor_plans:
            floor_columns = [
                col for col in solve_result.columns
                if col.get("floor") == fp.floor
            ]
            fp.columns = [
                ColumnPosition(x=c["x"], y=c["y"], width=c.get("width", 0.30), depth=c.get("depth", 0.30))
                for c in floor_columns
            ]

        floor_plan_dicts = [fp.model_dump() for fp in floor_plans]

        design = BuildingDesign(
            design_id=str(uuid.uuid4())[:8],
            project_id=req.project_id,
            jurisdiction=req.jurisdiction,
            num_floors=req.num_floors,
            plot_width=plot_info.width_m,
            plot_depth=plot_info.depth_m,
            north_direction_deg=plot_info.north_direction_deg,
            floor_plans=floor_plans,
            setback_front=setback_tuple[0],
            setback_rear=setback_tuple[1],
            setback_left=setback_tuple[2],
            setback_right=setback_tuple[3],
        )

        total_rooms = sum(len(fp.rooms) for fp in floor_plans)
        logger.info(
            "geometry_node: %d floor plans, %d total rooms, %d wall segments",
            len(floor_plans),
            total_rooms,
            sum(len(fp.wall_segments) for fp in floor_plans),
        )

        room_types = [
            r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type)
            for fp in floor_plans
            for r in fp.rooms
        ]
        event = {
            "node": "geometry",
            "type": "geometry_generated",
            "iteration": state.get("revision_count", 0),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "floor_count": len(floor_plans),
                "total_rooms": total_rooms,
                "room_types": room_types,
                "wall_segments": sum(len(fp.wall_segments) for fp in floor_plans),
            },
        }
        return {
            "floor_plans": floor_plan_dicts,
            "building_design": design.model_dump(),
            "warnings": warnings,
            "errors": errors,
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"geometry_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}
