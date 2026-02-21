"""
AgentState — the full pipeline state carried through the LangGraph graph.

All fields are Optional so nodes can run in isolation without requiring
previous nodes to have already populated their outputs.

Serialisation note: Pydantic models are stored as plain dicts (JSON-safe)
so they survive LangGraph's checkpoint serialisation (SqliteSaver / MemorySaver).
Use schema helpers like `PlotInfo.model_validate(state["plot_info"])` to
reconstruct typed objects inside nodes.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    # -----------------------------------------------------------------------
    # Project context
    # -----------------------------------------------------------------------
    project_id: str
    session_id: str
    project: dict | None          # serialised Project schema
    plot_info: dict | None        # serialised PlotInfo schema

    # -----------------------------------------------------------------------
    # Requirements (from interview)
    # -----------------------------------------------------------------------
    requirements: dict | None     # serialised DesignRequirements

    # -----------------------------------------------------------------------
    # Validation output
    # -----------------------------------------------------------------------
    validation_errors: list[str]     # blockers — solver will not run
    validation_warnings: list[str]   # advisories

    # -----------------------------------------------------------------------
    # Solver inputs / outputs
    # -----------------------------------------------------------------------
    buildable_zone: dict | None   # serialised Rect2D
    setbacks: list[float] | None  # [front, rear, left, right]
    solve_result: dict | None     # serialised SolveResult

    # -----------------------------------------------------------------------
    # Geometry output
    # -----------------------------------------------------------------------
    floor_plans: list[dict] | None       # list of serialised FloorPlan
    building_design: dict | None         # serialised BuildingDesign

    # -----------------------------------------------------------------------
    # Compliance / verification
    # -----------------------------------------------------------------------
    compliance_report: dict | None       # serialised ComplianceReport

    # -----------------------------------------------------------------------
    # Output artefacts
    # -----------------------------------------------------------------------
    output_dir: str | None               # path to session output directory
    dxf_paths: list[str] | None          # per-floor + combined DXF file paths
    pdf_paths: list[str] | None          # PDF design package paths
    cost_estimate: dict | None           # serialised CostEstimate
    report_path: str | None              # JSON compliance report path

    # -----------------------------------------------------------------------
    # Revision control
    # -----------------------------------------------------------------------
    revision_count: int
    should_revise: bool                     # set by verify_node

    # -----------------------------------------------------------------------
    # Conversation messages (add_messages reducer — never overwritten)
    # -----------------------------------------------------------------------
    messages: Annotated[list[BaseMessage], add_messages]

    # -----------------------------------------------------------------------
    # Pipeline diagnostics
    # -----------------------------------------------------------------------
    errors: list[str]
    warnings: list[str]


def make_initial_state(project_id: str, session_id: str) -> AgentState:
    """Create a fresh AgentState for a new design run."""
    return AgentState(
        project_id=project_id,
        session_id=session_id,
        project=None,
        plot_info=None,
        requirements=None,
        validation_errors=[],
        validation_warnings=[],
        buildable_zone=None,
        setbacks=None,
        solve_result=None,
        floor_plans=None,
        building_design=None,
        compliance_report=None,
        output_dir=None,
        dxf_paths=None,
        pdf_paths=None,
        cost_estimate=None,
        report_path=None,
        revision_count=0,
        should_revise=False,
        messages=[],
        errors=[],
        warnings=[],
    )
