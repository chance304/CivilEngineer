"""
human_review_node — human-in-the-loop pause before drawing.

Interrupts the graph and presents the engineer with:
  - Floor plan summary (room list, areas, adjacencies)
  - Any solver warnings

The engineer can:
  - Approve → pipeline continues to draw_node
  - Request changes → pipeline routes back to solve_node (with notes)
  - Abort → pipeline stops

Uses LangGraph's interrupt() — the graph pauses here and resumes
when the agent is invoked again with a Command(resume=...).
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from civilengineer.agent.state import AgentState
from civilengineer.schemas.design import FloorPlan

logger = logging.getLogger(__name__)


def human_review_node(state: AgentState) -> dict:
    """
    Pause for engineer review of the generated floor plan.

    Presents a text summary of all floors and rooms, then interrupts.
    On resume:
      - "approve" / "yes" / "ok"  → continues
      - "revise" / "no" / "change" → routes back to solve (with notes)
      - "abort" / "cancel"         → marks errors and stops
    """
    floor_plan_dicts = state.get("floor_plans") or []
    warnings         = list(state.get("warnings", []))
    errors           = list(state.get("errors", []))

    # Build summary text
    summary_lines = ["Floor plan summary:"]
    total_rooms = 0
    for fp_dict in floor_plan_dicts:
        try:
            fp = FloorPlan.model_validate(fp_dict)
            summary_lines.append(
                f"\nFloor {fp.floor} — {len(fp.rooms)} rooms "
                f"(buildable zone: {fp.buildable_zone.width:.1f}×{fp.buildable_zone.depth:.1f} m):"
            )
            for room in fp.rooms:
                summary_lines.append(
                    f"  • {room.name} ({room.room_type.value}) — "
                    f"{room.bounds.width:.1f}×{room.bounds.depth:.1f} m = {room.area:.1f} sqm"
                )
            total_rooms += len(fp.rooms)
        except Exception:
            summary_lines.append("  (floor data unavailable)")

    summary_lines.append(f"\nTotal rooms: {total_rooms}")

    if warnings:
        summary_lines.append("\nSolver warnings:")
        for w in warnings[-5:]:  # show last 5
            summary_lines.append(f"  ⚠  {w}")

    summary_lines.append(
        "\nReview the layout above. "
        "Reply 'approve' to proceed to drawing, "
        "'revise' to go back and adjust, "
        "or 'abort' to cancel."
    )

    summary_text = "\n".join(summary_lines)

    # Interrupt — engineer reviews and responds
    response = interrupt({"type": "human_review", "summary": summary_text})
    response_str = str(response).lower().strip() if response else "approve"

    messages = [
        AIMessage(content=summary_text),
        HumanMessage(content=str(response) if response else "approve"),
    ]

    if response_str.startswith(("abort", "cancel", "stop")):
        errors.append("Design aborted by engineer during human review.")
        return {
            "messages": messages,
            "errors": errors,
            "should_revise": False,
        }

    if response_str.startswith(("revise", "no", "change", "redo", "adjust")):
        warnings.append(f"Engineer requested revisions: {response}")
        return {
            "messages": messages,
            "warnings": warnings,
            "should_revise": True,
        }

    # Approved
    logger.info("human_review_node: engineer approved floor plan")
    return {
        "messages": messages,
        "should_revise": False,
        "warnings": warnings,
        "errors": errors,
    }
