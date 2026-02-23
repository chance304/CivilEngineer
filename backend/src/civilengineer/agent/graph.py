"""
Main LangGraph agent graph.

Full pipeline:

  START
    │
    ▼
  load_project     ← load Project + PlotInfo from DB
    │
    ▼ (interrupt — present requirements or start interview)
  interview        ← multi-turn requirements interview subgraph
    │
    ▼
  validate         ← cross-check requirements vs PlotInfo
    │
    ├─(hard errors)──► END
    │
    ▼
  plan             ← compute buildable zone; retrieve rules
    │
    ▼
  solve ──(UNSAT)──► relax ──┐
    │   ◄───────────────────┘  (loop ≤ 3 times)
    │
    ▼ (SAT / PARTIAL)
  geometry         ← SolveResult → FloorPlan + walls
    │
    ▼
  mep_routing      ← A* conduit routing + plumbing stacking
    │
    ▼ (interrupt — engineer reviews floor plan layout)
  human_review
    │
    ├─(should_revise)──► solve  (loop back)
    │
    ▼ (approved)
  draw             ← FloorPlan → DXF files
    │
    ▼
  verify           ← check_compliance → ComplianceReport
    │
    ├─(should_revise)──► relax ──► solve  (compliance-driven revision)
    │
    ▼
  save_output      ← write report.json; mark session complete
    │
    ▼
  END

Interrupt points (graph pauses for human input):
  - "interview" node (before asking first question)
  - "human_review" node (before engineer approves floor plan)

Usage
-----
    from civilengineer.agent.graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "project-123"}}

    # Initial run (hits interview interrupt)
    result = graph.invoke(initial_state, config=config)

    # Resume after engineer provides requirements
    from langgraph.types import Command
    result = graph.invoke(Command(resume="3BHK, 2 floors, modern"), config=config)
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from civilengineer.agent.nodes.draw_node import draw_node
from civilengineer.agent.nodes.geometry_node import geometry_node
from civilengineer.agent.nodes.human_review_node import human_review_node
from civilengineer.agent.nodes.load_project_node import load_project_node
from civilengineer.agent.nodes.mep_node import mep_routing_node
from civilengineer.agent.nodes.plan_node import plan_node
from civilengineer.agent.nodes.relax_node import relax_node
from civilengineer.agent.nodes.save_output_node import save_output_node
from civilengineer.agent.nodes.solve_node import solve_node
from civilengineer.agent.nodes.validate_node import validate_node
from civilengineer.agent.nodes.verify_node import verify_node
from civilengineer.agent.state import AgentState

logger = logging.getLogger(__name__)

_MAX_SOLVE_RELAX_LOOPS   = 3
_MAX_VERIFY_REVISE_LOOPS = 2


# ---------------------------------------------------------------------------
# Inline interview node (wraps interview subgraph + interrupt)
# ---------------------------------------------------------------------------


def interview_node(state: AgentState) -> dict:
    """
    Interrupt point: collect DesignRequirements from the engineer.

    If requirements are already in state (from a previous session or
    the interview subgraph already ran), skip immediately.

    Otherwise interrupt and wait for the engineer to supply a plain-text
    requirements description (e.g. "3BHK, 2 floors, modern, Vastu").
    The answer is parsed by the questions module.
    """
    if state.get("requirements"):
        logger.info("interview_node: requirements already set; skipping.")
        return {}

    from langchain_core.messages import AIMessage, HumanMessage  # noqa: PLC0415

    from civilengineer.requirements_interview.questions import (  # noqa: PLC0415
        answers_to_requirements,
        extract_bhk,
        extract_bool,
        extract_num_floors,
        extract_special_rooms,
        extract_style,
    )

    plot_info = state.get("plot_info")
    project_id = state.get("project_id", "")

    # Build greeting
    if plot_info:
        area = plot_info.get("area_sqm", 0)
        facing = plot_info.get("facing", "unknown")
        prompt = (
            f"Your plot is {area:.0f} sqm, {facing} facing.\n\n"
            "Please describe your requirements:\n"
            "  • Building type (residential/commercial)\n"
            "  • Number of floors (e.g. 2 floors, G+1)\n"
            "  • Rooms (e.g. 3BHK, or '3 bedrooms 2 bathrooms')\n"
            "  • Style (Modern/Traditional/Minimal/Newari)\n"
            "  • Vastu? (yes/no)\n"
            "  • Special rooms (home office, garage, pooja room, etc.)\n"
            "  • Any other notes"
        )
    else:
        prompt = (
            "Please describe your building requirements:\n"
            "  • Building type · Number of floors · BHK config\n"
            "  • Architectural style · Vastu? · Special rooms · Notes"
        )

    response = interrupt({"type": "interview", "prompt": prompt})
    raw = str(response).strip() if response else ""

    # Parse the free-text response using extractors
    answers: dict = {}
    answers["building_type"]  = "residential"
    answers["num_floors"]     = extract_num_floors(raw)
    answers["bhk_config"]     = extract_bhk(raw)
    answers["master_bedroom"] = True
    answers["style"]          = extract_style(raw)
    answers["vastu"]          = extract_bool(raw) if "vastu" in raw.lower() else False
    answers["special_rooms"]  = extract_special_rooms(raw)
    answers["notes"]          = ""

    req_dict = answers_to_requirements(
        answers, project_id,
        road_width_m=plot_info.get("road_width_m") if plot_info else None,
    )

    return {
        "requirements": req_dict,
        "messages": [
            AIMessage(content=prompt),
            HumanMessage(content=raw),
        ],
    }


# ---------------------------------------------------------------------------
# Edge condition functions
# ---------------------------------------------------------------------------


def _after_validate(state: AgentState) -> Literal["plan", "__end__"]:
    """Route to END if hard validation errors exist, otherwise continue."""
    if state.get("validation_errors"):
        logger.warning("Validation failed; aborting: %s", state["validation_errors"])
        return "__end__"
    return "plan"


def _after_solve(state: AgentState) -> Literal["geometry", "relax"]:
    """Route to relax if solver returned UNSAT, otherwise proceed to geometry."""
    solve_dict = state.get("solve_result")
    if not solve_dict:
        return "relax"
    status = solve_dict.get("status", "SAT")
    if status == "UNSAT":
        return "relax"
    return "geometry"


def _after_relax(state: AgentState) -> Literal["solve", "__end__"]:
    """Route back to solve unless max relaxation attempts exceeded."""
    revision = state.get("revision_count", 0)
    errors   = state.get("errors", [])
    if any("Relaxation failed" in e for e in errors):
        return "__end__"
    if revision >= _MAX_SOLVE_RELAX_LOOPS:
        return "__end__"
    return "solve"


def _after_human_review(state: AgentState) -> Literal["draw", "solve", "__end__"]:
    """
    After human review:
      - abort (errors set)  → END
      - revise requested    → back to solve
      - approved            → draw
    """
    errors = state.get("errors", [])
    if any("aborted" in e.lower() for e in errors):
        return "__end__"
    if state.get("should_revise"):
        return "solve"
    return "draw"


def _after_verify(state: AgentState) -> Literal["save_output", "relax"]:
    """Route to relax if compliance failures and under revision limit."""
    if state.get("should_revise"):
        return "relax"
    return "save_output"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(checkpointer=None):
    """
    Build and compile the full pipeline LangGraph graph.

    Args:
        checkpointer : LangGraph checkpointer (MemorySaver, SqliteSaver, etc.)
                       If None, a new MemorySaver is created.

    Returns:
        Compiled LangGraph graph.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("load_project",  load_project_node)
    builder.add_node("interview",     interview_node)
    builder.add_node("validate",      validate_node)
    builder.add_node("plan",          plan_node)
    builder.add_node("solve",         solve_node)
    builder.add_node("relax",         relax_node)
    builder.add_node("geometry",      geometry_node)
    builder.add_node("mep_routing",   mep_routing_node)
    builder.add_node("human_review",  human_review_node)
    builder.add_node("draw",          draw_node)
    builder.add_node("verify",        verify_node)
    builder.add_node("save_output",   save_output_node)

    # Entry point
    builder.set_entry_point("load_project")

    # Linear edges
    builder.add_edge("load_project", "interview")
    builder.add_edge("interview",    "validate")
    builder.add_edge("plan",         "solve")
    builder.add_edge("geometry",     "mep_routing")
    builder.add_edge("mep_routing",  "human_review")
    builder.add_edge("draw",         "verify")
    builder.add_edge("save_output",  END)

    # Conditional edges
    builder.add_conditional_edges(
        "validate", _after_validate,
        {"plan": "plan", "__end__": END},
    )
    builder.add_conditional_edges(
        "solve", _after_solve,
        {"geometry": "geometry", "relax": "relax"},
    )
    builder.add_conditional_edges(
        "relax", _after_relax,
        {"solve": "solve", "__end__": END},
    )
    builder.add_conditional_edges(
        "human_review", _after_human_review,
        {"draw": "draw", "solve": "solve", "__end__": END},
    )
    builder.add_conditional_edges(
        "verify", _after_verify,
        {"save_output": "save_output", "relax": "relax"},
    )

    return builder.compile(checkpointer=checkpointer)
