"""
solve_node — Layer 2 (constraint solver).

Calls constraint_solver.solve_layout() with the buildable zone and rules.
Sets state["solve_result"] and appends any solver warnings to state["warnings"].

Rule loading priority:
  1. DB-first via load_rules_from_db(session, jurisdiction) — uses the project's
     jurisdiction to load only the relevant active rules from PostgreSQL.
  2. Bundled JSON fallback via load_rules(jurisdiction=...) — used when the DB
     has no rules for that jurisdiction, a DB session is unavailable,
     or the function is called from a context with no running event loop
     (e.g. unit tests).

solve_node remains a sync function so it is compatible with existing tests
and Celery workers (neither of which runs an event loop when calling the node).
LangGraph's StateGraph handles sync nodes correctly in both sync and async graphs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from civilengineer.agent.state import AgentState
from civilengineer.knowledge.rule_compiler import load_rules, load_rules_from_db
from civilengineer.reasoning_engine.constraint_solver import SolveStatus, solve_layout
from civilengineer.schemas.design import DesignRequirements, Rect2D
from civilengineer.schemas.rules import DesignRule

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30.0
_FALLBACK_JURISDICTION = "NP-KTM"


def solve_node(state: AgentState) -> dict:
    """Run the CP-SAT constraint solver with jurisdiction-aware rule loading."""
    req_dict = state.get("requirements")
    zone_dict = state.get("buildable_zone")
    errors = list(state.get("errors", []))
    warnings = list(state.get("warnings", []))

    if not req_dict:
        errors.append("solve_node: no requirements in state.")
        return {"errors": errors}

    if not zone_dict:
        errors.append("solve_node: no buildable_zone in state — run plan_node first.")
        return {"errors": errors}

    try:
        req = DesignRequirements.model_validate(req_dict)
        zone = Rect2D.model_validate(zone_dict)

        # Resolve jurisdiction from project state; fall back to NP-KTM for MVP
        jurisdiction: str = (
            (state.get("project") or {}).get("jurisdiction")
            or _FALLBACK_JURISDICTION
        )

        rules = _load_rules(jurisdiction)

        result = solve_layout(req, zone, rules, timeout_s=_DEFAULT_TIMEOUT_S)

        warnings.extend(result.warnings)
        logger.info(
            "Solver: status=%s placed=%d unplaced=%d time=%.2fs jurisdiction=%s",
            result.status,
            len(result.placed_rooms),
            len(result.unplaced_rooms),
            result.solver_time_s,
            jurisdiction,
        )

        if result.status == SolveStatus.UNSAT:
            errors.append(
                f"Constraint solver returned UNSAT: rooms cannot fit in "
                f"{zone.width:.1f}×{zone.depth:.1f} m buildable zone. "
                "Try relax_node or reduce room count."
            )

        event = {
            "node": "solve",
            "type": "solver_run",
            "iteration": state.get("revision_count", 0),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {
                "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                "placed_count": len(result.placed_rooms),
                "unplaced_count": len(result.unplaced_rooms),
                "solver_time_s": result.solver_time_s,
                "unplaced_rooms": [
                    r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type)
                    for r in result.unplaced_rooms
                ],
                "warnings": result.warnings,
            },
        }
        return {
            "solve_result": result.model_dump(),
            "warnings": warnings,
            "errors": errors,
            "decision_events": [event],
        }

    except Exception as exc:
        msg = f"solve_node error: {exc}"
        logger.exception(msg)
        errors.append(msg)
        return {"errors": errors}


def _load_rules(jurisdiction: str) -> list[DesignRule]:
    """
    Load rules with DB-first strategy; fall back to bundled JSON.

    Uses asyncio.run() to execute the async DB query.  This is safe because:
    - Unit tests run with no event loop.
    - Celery workers (default pool) have no event loop in the task thread.
    - LangGraph runs sync nodes in a thread pool executor (no loop there either).

    If an event loop is already running (e.g. in an async test or nested call),
    we transparently fall back to the bundled JSON rather than blocking.
    """
    try:
        return asyncio.run(_load_rules_async(jurisdiction))
    except RuntimeError:
        # An event loop is already running — cannot nest asyncio.run().
        # Fall back to the bundled JSON synchronously.
        logger.debug(
            "solve_node: event loop already running; skipping DB load for %s.",
            jurisdiction,
        )
        return load_rules(jurisdiction=jurisdiction).rules
    except Exception as exc:
        logger.warning(
            "solve_node: DB rule loading failed (%s); falling back to bundled JSON.",
            exc,
        )
        return load_rules(jurisdiction=jurisdiction).rules


async def _load_rules_async(jurisdiction: str) -> list[DesignRule]:
    """Open a short-lived DB session and load rules for the jurisdiction."""
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        rule_set = await load_rules_from_db(session, jurisdiction)
        return rule_set.rules
