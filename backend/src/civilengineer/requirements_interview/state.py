"""
InterviewState — state carried through the requirements interview subgraph.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class InterviewState(TypedDict, total=False):
    # Project context passed in from AgentState
    project_id: str
    plot_info: dict | None            # serialised PlotInfo

    # Accumulated answers keyed by question_id
    answers: dict[str, Any]

    # Conversation history
    messages: Annotated[list[BaseMessage], add_messages]

    # Current interview phase
    current_phase: str   # see Phase constants below

    # Whether the interview is finished
    is_complete: bool

    # Final output — serialised DesignRequirements
    requirements: dict | None

    # Non-blocking warnings the LLM flagged during the interview
    interview_warnings: list[str]


# Interview phases (in order)
PHASE_GREET         = "greet"
PHASE_BUILDING_TYPE = "building_type"
PHASE_PROGRAM       = "program"
PHASE_ROOMS         = "rooms"
PHASE_STYLE         = "style"
PHASE_VASTU         = "vastu"
PHASE_SPECIAL       = "special"
PHASE_CONSTRAINTS   = "constraints"
PHASE_CONFIRM       = "confirm"
PHASE_COMPLETE      = "complete"

PHASE_ORDER = [
    PHASE_GREET,
    PHASE_BUILDING_TYPE,
    PHASE_PROGRAM,
    PHASE_ROOMS,
    PHASE_STYLE,
    PHASE_VASTU,
    PHASE_SPECIAL,
    PHASE_CONSTRAINTS,
    PHASE_CONFIRM,
    PHASE_COMPLETE,
]
