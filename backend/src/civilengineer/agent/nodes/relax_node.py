"""
relax_node — relaxation after UNSAT.

When the constraint solver cannot place all rooms, this node applies a
relaxation strategy and marks state so solve_node can be retried:

Relaxation strategies (applied in order):
  1. Remove optional rooms (balcony, terrace, store, corridor)
  2. Remove the last special room (home_office, pooja_room, garage)
  3. Reduce bedroom count by 1 (warn user)
  4. If still stuck after 3 attempts, raise an error

The revised requirements are written back to state["requirements"].
state["revision_count"] tracks how many times we've relaxed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.messages import AIMessage

from civilengineer.agent.state import AgentState
from civilengineer.schemas.design import DesignRequirements, RoomRequirement, RoomType

logger = logging.getLogger(__name__)

_MAX_REVISIONS = 3

# Rooms that can be dropped first (least critical)
_OPTIONAL_TYPES = frozenset({
    RoomType.BALCONY,
    RoomType.TERRACE,
    RoomType.CORRIDOR,
    RoomType.STORE,
})

# Secondary optional types
_SECONDARY_OPTIONAL = frozenset({
    RoomType.HOME_OFFICE,
    RoomType.POOJA_ROOM,
    RoomType.GARAGE,
})


def relax_node(state: AgentState) -> dict:
    """Apply a relaxation and update requirements for solver retry."""
    req_dict       = state.get("requirements", {})
    revision_count = state.get("revision_count", 0)
    errors         = list(state.get("errors", []))
    warnings       = list(state.get("warnings", []))

    if revision_count >= _MAX_REVISIONS:
        errors.append(
            f"Relaxation failed after {_MAX_REVISIONS} attempts. "
            "The plot is too small for the requested room program. "
            "Please reduce the number of rooms or increase the plot size."
        )
        return {"errors": errors, "revision_count": revision_count}

    try:
        req   = DesignRequirements.model_validate(req_dict)
        rooms = list(req.rooms)

        relaxation_msg, rooms = _apply_relaxation(rooms, revision_count, warnings)

        req.rooms = rooms
        new_req_dict = req.model_dump()

        logger.info(
            "relax_node (attempt %d): %s → %d rooms remaining",
            revision_count + 1, relaxation_msg, len(rooms),
        )

        rooms_before = [
            r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type)
            for r in DesignRequirements.model_validate(req_dict).rooms
        ]
        rooms_after = [
            r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type)
            for r in rooms
        ]
        rooms_removed = [rt for rt in rooms_before if rt not in rooms_after]

        event = {
            "node": "relax",
            "type": "relaxation_applied",
            "iteration": revision_count,
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "relaxation_type": relaxation_msg,
                "rooms_removed": rooms_removed,
                "revision_count": revision_count + 1,
                "status": "UNSAT",  # relax is always triggered by UNSAT
                "placed_count": 0,
                "unplaced_count": len(rooms_before),
                "solver_time_s": 0.0,
                "warnings": warnings,
            },
        }
        return {
            "requirements": new_req_dict,
            "revision_count": revision_count + 1,
            "warnings": warnings,
            "errors": [e for e in errors if "UNSAT" not in e],  # clear UNSAT error
            "messages": [AIMessage(content=f"Relaxation applied: {relaxation_msg}")],
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"relax_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}


def _apply_relaxation(
    rooms: list[RoomRequirement],
    revision: int,
    warnings: list[str],
) -> tuple[str, list[RoomRequirement]]:
    """
    Apply the next relaxation step. Returns (message, updated_rooms).
    """
    # Revision 0: remove optional rooms
    if revision == 0:
        before = len(rooms)
        rooms = [r for r in rooms if r.room_type not in _OPTIONAL_TYPES]
        removed = before - len(rooms)
        if removed > 0:
            msg = f"Removed {removed} optional room(s) (balcony/terrace/store/corridor)."
            warnings.append(msg)
            return msg, rooms

    # Revision 1: remove secondary optional rooms
    if revision <= 1:
        for rtype in _SECONDARY_OPTIONAL:
            matching = [r for r in rooms if r.room_type == rtype]
            if matching:
                rooms = [r for r in rooms if r is not matching[-1]]
                msg = f"Removed 1 {rtype.value.replace('_', ' ')} to fit within buildable zone."
                warnings.append(msg)
                return msg, rooms

    # Revision 2: reduce bedroom count by 1
    bedroom_types = [RoomType.BEDROOM, RoomType.MASTER_BEDROOM]
    for rtype in bedroom_types:
        matching = [r for r in rooms if r.room_type == rtype]
        if len(matching) > 1:
            rooms = [r for r in rooms if r is not matching[-1]]
            msg = f"Reduced {rtype.value.replace('_', ' ')} count by 1 to fit within buildable zone."
            warnings.append(msg)
            return msg, rooms

    # Nothing could be relaxed
    msg = "No further relaxation possible."
    warnings.append(msg)
    return msg, rooms
