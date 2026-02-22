"""
draw_node — Layer 4/5 (DXF + PDF generation).

Generates per-floor DXF drawings, a combined layout DXF, a site plan DXF,
and a PDF design package.  AutoCAD COM bridge is Phase 7 (used automatically
on Windows when AutoCAD is running; ezdxf fallback on Linux / CI).

Output files are written to state["output_dir"] / session_id /:
  floor_1.dxf, floor_2.dxf, …   — per-floor plans
  combined_floors.dxf            — all floors tiled side by side
  site_plan.dxf                  — plot + setbacks + ground footprint
  floor_index.dxf                — index / cover sheet
  design_package.pdf             — full PDF package
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage

from civilengineer.agent.state import AgentState
from civilengineer.cad_layer.ezdxf_driver import EzdxfDriver
from civilengineer.cad_layer.oda_converter import convert_to_dwg
from civilengineer.output_layer.cost_estimator import CostEstimator
from civilengineer.output_layer.dxf_exporter import DXFExporter
from civilengineer.output_layer.ifc_exporter import IFCExporter
from civilengineer.output_layer.pdf_exporter import PDFExporter
from civilengineer.schemas.design import BuildingDesign, FloorPlan

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = "output"


def draw_node(state: AgentState) -> dict:
    """Generate DXF floor plan files and PDF design package from the building design."""
    building_dict    = state.get("building_design")
    floor_plan_dicts = state.get("floor_plans") or []
    session_id       = state.get("session_id", "session")
    output_dir_str   = state.get("output_dir") or _DEFAULT_OUTPUT_DIR
    plot_info        = state.get("plot_info")
    setbacks         = state.get("setbacks")
    requirements     = state.get("requirements", {})
    errors           = list(state.get("errors", []))
    warnings         = list(state.get("warnings", []))

    if not building_dict:
        errors.append("draw_node: no building_design in state.")
        return {"errors": errors}

    if not floor_plan_dicts:
        errors.append("draw_node: no floor_plans in state.")
        return {"errors": errors}

    try:
        building  = BuildingDesign.model_validate(building_dict)
        out_dir   = Path(output_dir_str) / session_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------ #
        # 1. Per-floor DXF (original draw_node behaviour)
        # ------------------------------------------------------------------ #
        driver    = EzdxfDriver()
        dxf_paths: list[str] = []

        # Rebuild full floor_plan list in building for exporter
        all_fps: list[FloorPlan] = []
        for fp_dict in floor_plan_dicts:
            fp = FloorPlan.model_validate(fp_dict)
            all_fps.append(fp)
            # Per-floor: inject only this floor so driver builds it correctly
            building.floor_plans = [fp]
            out_path = out_dir / f"floor_{fp.floor}.dxf"
            driver.render_floor_plan(fp, building, out_path)
            dxf_paths.append(str(out_path))
            logger.info("draw_node: wrote %s", out_path)

        # Restore full floor list on building
        building.floor_plans = all_fps

        # ------------------------------------------------------------------ #
        # 2. Combined / site plan / index DXF (Phase 8)
        # ------------------------------------------------------------------ #
        exporter = DXFExporter()

        combined_path = exporter.export_combined(building, out_dir)
        dxf_paths.append(str(combined_path))

        site_path = exporter.export_site_plan(
            building,
            plot_info=plot_info,
            setbacks=tuple(setbacks) if setbacks else None,
            output_dir=out_dir,
        )
        dxf_paths.append(str(site_path))

        index_path = exporter.export_floor_index(building, dxf_paths, out_dir)
        dxf_paths.append(str(index_path))

        # ------------------------------------------------------------------ #
        # 3. Cost estimate
        # ------------------------------------------------------------------ #
        material_grade = requirements.get("style", "standard")
        # Map style preference to material grade
        _style_to_grade = {
            "modern": "standard", "minimal": "standard",
            "traditional": "basic", "newari": "basic",
            "classical": "premium",
        }
        grade = _style_to_grade.get(str(material_grade).lower(), "standard")
        estimator = CostEstimator(material_grade=grade)  # type: ignore[arg-type]
        cost_estimate = estimator.estimate(building)
        cost_dict = cost_estimate.model_dump()

        # ------------------------------------------------------------------ #
        # 4. PDF design package (Phase 8)
        # ------------------------------------------------------------------ #
        project_id   = state.get("project_id", "")
        project_name = (state.get("project") or {}).get("name", project_id)
        client_name  = (state.get("project") or {}).get("client_name", "")

        pdf_exporter = PDFExporter()
        pdf_path = pdf_exporter.export(
            building=building,
            output_dir=out_dir,
            project_name=project_name,
            client_name=client_name,
            cost_estimate=cost_estimate,
        )
        pdf_paths = [str(pdf_path)]
        logger.info("draw_node: wrote PDF %s", pdf_path)

        # ------------------------------------------------------------------ #
        # 5. IFC export (best-effort; requires ifcopenshell)
        # ------------------------------------------------------------------ #
        ifc_result = IFCExporter().export(building, out_dir)
        ifc_path: str | None = str(ifc_result) if ifc_result else None
        if ifc_path:
            logger.info("draw_node: wrote IFC %s", ifc_path)

        # ------------------------------------------------------------------ #
        # 6. DWG conversion (best-effort; requires ODA binary)
        # ------------------------------------------------------------------ #
        dwg_paths: list[str] = []
        floor_dxf_paths = [p for p in dxf_paths if Path(p).name.startswith("floor_")]
        for dxf_path_str in floor_dxf_paths:
            dwg = convert_to_dwg(Path(dxf_path_str))
            if dwg:
                dwg_paths.append(str(dwg))
                logger.info("draw_node: DWG converted %s", dwg)

        # ------------------------------------------------------------------ #
        # 7. Summary message
        # ------------------------------------------------------------------ #
        extra_formats = []
        if ifc_path:
            extra_formats.append(f"  • IFC: {ifc_path}")
        for dwg in dwg_paths:
            extra_formats.append(f"  • DWG: {dwg}")

        summary = (
            f"Generated {len([p for p in dxf_paths if p.endswith('.dxf')])} DXF file(s) "
            f"+ 1 PDF:\n"
            + "\n".join(f"  • {p}" for p in dxf_paths + pdf_paths)
            + ("\n" + "\n".join(extra_formats) if extra_formats else "")
            + f"\n\nCost estimate ({grade}): {cost_estimate.formatted_total()}"
        )

        event = {
            "node": "draw",
            "type": "cad_generated",
            "iteration": state.get("revision_count", 0),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "dxf_paths": dxf_paths,
                "pdf_paths": pdf_paths,
                "ifc_path": ifc_path,
                "dwg_paths": dwg_paths,
                "num_floors": building.num_floors,
                "roof_type": getattr(building, "roof_type", ""),
                "facade_material": grade,
                "floor_heights": [],
            },
        }
        return {
            "dxf_paths":    dxf_paths,
            "pdf_paths":    pdf_paths,
            "ifc_path":     ifc_path,
            "dwg_paths":    dwg_paths or None,
            "cost_estimate": cost_dict,
            "output_dir":   str(out_dir),
            "messages":     [AIMessage(content=summary)],
            "warnings":     warnings,
            "errors":       errors,
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"draw_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}
