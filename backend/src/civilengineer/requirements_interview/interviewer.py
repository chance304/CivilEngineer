"""
Requirements interview subgraph.

Implements a structured multi-turn conversation using LangGraph.
The LLM asks questions and parses user responses; deterministic
extractor functions convert free-text answers to typed values.

Graph structure
---------------

  START
    │
    ▼
  ask          ← format and present the next question to the user
    │
    ▼ (interrupt — wait for human input)
  parse        ← extract typed answer from human response
    │
    ├─(more questions)──► ask
    │
    ▼ (all questions answered)
  confirm      ← show summary, ask for confirmation
    │
    ├─(user wants changes)──► ask (restart from rooms phase)
    │
    ▼ (confirmed)
  build_req    ← assemble DesignRequirements from answers
    │
    ▼
  END

interrupt_before = ["ask"]  — pauses for human input before every question.

Usage
-----
    from civilengineer.requirements_interview.interviewer import build_interview_graph
    graph = build_interview_graph()
    config = {"configurable": {"thread_id": project_id}}
    state  = graph.invoke(initial_state, config=config)
    # After interrupt, resume with:
    state  = graph.invoke(Command(resume=user_text), config=config)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from civilengineer.requirements_interview.questions import (
    QUESTION_BY_ID,
    answers_to_requirements,
    get_feasibility_warnings,
    questions_for_phase,
)
from civilengineer.requirements_interview.state import (
    PHASE_BUILDING_TYPE,
    PHASE_COMPLETE,
    PHASE_CONFIRM,
    PHASE_CONSTRAINTS,
    PHASE_PROGRAM,
    PHASE_ROOMS,
    PHASE_SPECIAL,
    PHASE_STYLE,
    PHASE_VASTU,
    InterviewState,
)
from civilengineer.schemas.design import DesignRequirements

logger = logging.getLogger(__name__)

# Phases in order (excluding greet and complete — handled separately)
_QUESTION_PHASES = [
    PHASE_BUILDING_TYPE,
    PHASE_PROGRAM,
    PHASE_ROOMS,
    PHASE_STYLE,
    PHASE_VASTU,
    PHASE_SPECIAL,
    PHASE_CONSTRAINTS,
]


# ---------------------------------------------------------------------------
# Node: greet
# ---------------------------------------------------------------------------


def greet_node(state: InterviewState) -> dict:
    """Generate a greeting message and move to the first question phase."""
    plot_info = state.get("plot_info")

    if plot_info:
        area = plot_info.get("area_sqm", 0)
        facing = plot_info.get("facing", "unknown")
        greeting = (
            f"Welcome! I'm ready to design your building. "
            f"Your plot is {area:.0f} sqm with {facing} facing. "
            f"Let me ask you a few questions to understand your requirements."
        )
    else:
        greeting = (
            "Welcome! I'm ready to design your building. "
            "Let me ask you a few questions to understand your requirements."
        )

    return {
        "messages": [AIMessage(content=greeting)],
        "current_phase": PHASE_BUILDING_TYPE,
        "answers": state.get("answers", {}),
        "interview_warnings": [],
    }


# ---------------------------------------------------------------------------
# Node: ask
# ---------------------------------------------------------------------------


def ask_node(state: InterviewState) -> dict:
    """
    Present the next unanswered question to the user.
    Uses interrupt() to pause and wait for human input.
    """
    answers = state.get("answers", {})
    phase = state.get("current_phase", PHASE_BUILDING_TYPE)

    # Find the next unanswered question
    question = _next_unanswered_question(phase, answers)

    if question is None:
        # All questions in current phase done — advance to next phase
        next_phase = _next_phase(phase, answers)
        if next_phase == PHASE_CONFIRM:
            return {"current_phase": PHASE_CONFIRM}
        elif next_phase == PHASE_COMPLETE:
            return {"current_phase": PHASE_COMPLETE, "is_complete": True}
        else:
            return {"current_phase": next_phase}

    # Present question to user
    msg = question.prompt
    if question.help_text:
        msg += f"\n  (Tip: {question.help_text})"

    # interrupt() pauses graph execution; resumes when user provides input
    user_response = interrupt({"question_id": question.id, "prompt": msg})

    return {
        "messages": [
            AIMessage(content=msg),
            HumanMessage(content=str(user_response) if user_response else ""),
        ],
        "_pending_question_id": question.id,
        "_pending_answer_raw": str(user_response) if user_response else "",
    }


# ---------------------------------------------------------------------------
# Node: parse
# ---------------------------------------------------------------------------


def parse_node(state: InterviewState) -> dict:
    """Extract typed answer from the pending raw response and store it."""
    question_id = state.get("_pending_question_id")
    raw_answer  = state.get("_pending_answer_raw", "")

    if not question_id:
        return {}

    question = QUESTION_BY_ID.get(question_id)
    if not question:
        return {}

    answers = dict(state.get("answers", {}))

    # Extract typed value
    if question.extractor:
        try:
            typed_value = question.extractor(raw_answer)
            answers[question_id] = typed_value
        except Exception as exc:
            logger.warning("Extractor failed for %s: %s", question_id, exc)
            answers[question_id] = raw_answer  # store raw as fallback
    else:
        answers[question_id] = raw_answer

    # Check for feasibility warnings after rooms phase
    warnings = list(state.get("interview_warnings", []))
    if question.phase == PHASE_ROOMS:
        plot_info = state.get("plot_info")
        area = plot_info.get("area_sqm") if plot_info else None
        new_warnings = get_feasibility_warnings(answers, area)
        warnings.extend(new_warnings)

    return {
        "answers": answers,
        "interview_warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Node: confirm
# ---------------------------------------------------------------------------


def confirm_node(state: InterviewState) -> dict:
    """Show summary of collected requirements and ask for confirmation."""
    answers = state.get("answers", {})
    project_id = state.get("project_id", "")
    plot_info = state.get("plot_info")

    road_width = plot_info.get("road_width_m") if plot_info else None

    try:
        req_dict = answers_to_requirements(
            answers, project_id, road_width_m=road_width
        )
        req = DesignRequirements.model_validate(req_dict)
        summary = _format_requirements_summary(req)
    except Exception as exc:
        summary = f"(Could not format summary: {exc})"
        req_dict = None

    confirm_prompt = (
        f"{summary}\n\n"
        "Does this look correct? (yes to proceed, no to make changes)"
    )

    user_response = interrupt({"question_id": "confirm", "prompt": confirm_prompt})
    confirmed = _extract_bool(str(user_response) if user_response else "yes")

    if confirmed:
        return {
            "messages": [
                AIMessage(content=confirm_prompt),
                HumanMessage(content=str(user_response) if user_response else "yes"),
            ],
            "current_phase": PHASE_COMPLETE,
            "is_complete": True,
            "requirements": req_dict,
        }
    else:
        # Restart from rooms phase
        return {
            "messages": [
                AIMessage(content=confirm_prompt),
                HumanMessage(content=str(user_response) if user_response else "no"),
                AIMessage(content="No problem — let's go over the room configuration again."),
            ],
            "current_phase": PHASE_ROOMS,
            "answers": {k: v for k, v in answers.items() if k not in
                        ("bhk_config", "master_bedroom", "special_rooms")},
        }


# ---------------------------------------------------------------------------
# Node: build_requirements
# ---------------------------------------------------------------------------


def build_requirements_node(state: InterviewState) -> dict:
    """Assemble final DesignRequirements from collected answers."""
    if state.get("requirements"):
        return {}  # already set in confirm_node

    answers = state.get("answers", {})
    project_id = state.get("project_id", "")
    plot_info = state.get("plot_info")
    road_width = plot_info.get("road_width_m") if plot_info else None

    req_dict = answers_to_requirements(answers, project_id, road_width_m=road_width)

    return {
        "requirements": req_dict,
        "is_complete": True,
        "current_phase": PHASE_COMPLETE,
    }


# ---------------------------------------------------------------------------
# Edge routing
# ---------------------------------------------------------------------------


def _route_after_ask(state: InterviewState) -> str:
    """After ask_node: always go to parse."""
    return "parse"


def _route_after_parse(state: InterviewState) -> str:
    """After parse_node: loop back to ask or advance to confirm/complete."""
    phase = state.get("current_phase", PHASE_BUILDING_TYPE)
    if phase == PHASE_CONFIRM:
        return "confirm"
    if phase == PHASE_COMPLETE:
        return "build_requirements"
    return "ask"


def _route_after_confirm(state: InterviewState) -> str:
    phase = state.get("current_phase", PHASE_COMPLETE)
    if phase == PHASE_COMPLETE:
        return "build_requirements"
    return "ask"  # user said no — restart rooms


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_interview_graph() -> StateGraph:
    """
    Build and compile the requirements interview subgraph.

    Returns a compiled LangGraph graph. Callers should supply a
    MemorySaver / SqliteSaver checkpointer for resumable sessions.
    """
    builder = StateGraph(InterviewState)

    builder.add_node("greet",              greet_node)
    builder.add_node("ask",                ask_node)
    builder.add_node("parse",              parse_node)
    builder.add_node("confirm",            confirm_node)
    builder.add_node("build_requirements", build_requirements_node)

    builder.set_entry_point("greet")
    builder.add_edge("greet", "ask")
    builder.add_edge("ask",   "parse")

    builder.add_conditional_edges("parse", _route_after_parse, {
        "ask":                "ask",
        "confirm":            "confirm",
        "build_requirements": "build_requirements",
    })
    builder.add_conditional_edges("confirm", _route_after_confirm, {
        "build_requirements": "build_requirements",
        "ask":                "ask",
    })
    builder.add_edge("build_requirements", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_unanswered_question(
    phase: str, answers: dict[str, Any]
):
    """Find the first unanswered question in the given phase."""
    for q in questions_for_phase(phase, answers):
        if q.id not in answers:
            return q
    return None


def _next_phase(phase: str, answers: dict[str, Any]) -> str:
    """Return the next phase after the given phase."""
    try:
        idx = _QUESTION_PHASES.index(phase)
        # Check if there are any active questions in subsequent phases
        for next_phase in _QUESTION_PHASES[idx + 1:]:
            active = questions_for_phase(next_phase, answers)
            if active:
                return next_phase
    except ValueError:
        pass
    return PHASE_CONFIRM


def _format_requirements_summary(req: DesignRequirements) -> str:
    """Format DesignRequirements as a human-readable summary."""
    room_counts: dict[str, int] = {}
    for r in req.rooms:
        room_counts[r.room_type.value] = room_counts.get(r.room_type.value, 0) + 1

    room_lines = "\n".join(
        f"  • {count}× {rtype.replace('_', ' ').title()}"
        for rtype, count in sorted(room_counts.items())
    )

    lines = [
        "Here is what I understood:",
        f"  Floors    : {req.num_floors}",
        f"  Style     : {req.style.value.title()}",
        f"  Vastu     : {'Yes' if req.vastu_compliant else 'No'}",
        "  Rooms:",
        room_lines,
    ]
    if req.notes:
        lines.append(f"  Notes     : {req.notes}")
    return "\n".join(lines)


def _extract_bool(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith(("y", "yes", "true", "1", "ok", "sure", "correct", "confirm"))
