"""
session_store — Durable LangGraph checkpoint persistence.

Maps design session_ids → LangGraph thread_ids backed by SqliteSaver.
Each Celery worker shares the same SQLite DB on the local filesystem;
for multi-host deployments upgrade to PostgresSaver.

Usage
-----
    from civilengineer.agent.session_store import (
        build_persistent_graph, session_to_thread_id, get_sessions_db_path
    )

    graph  = build_persistent_graph()
    config = {"configurable": {"thread_id": session_to_thread_id(session_id)}}
    result = graph.invoke(initial_state, config=config)
"""

from __future__ import annotations

import logging
from pathlib import Path

from civilengineer.agent.graph import build_graph

logger = logging.getLogger(__name__)

_DEFAULT_SESSIONS_DIR = Path("sessions")
_DB_FILENAME           = "agent_sessions.db"

# --------------------------------------------------------------------- #
# Public helpers                                                         #
# --------------------------------------------------------------------- #


def get_sessions_db_path(base_dir: str | Path | None = None) -> Path:
    """Return the absolute path to the LangGraph SQLite checkpoint DB.

    Creates the parent directory if it does not exist.
    """
    directory = Path(base_dir) if base_dir else _DEFAULT_SESSIONS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _DB_FILENAME


def session_to_thread_id(session_id: str) -> str:
    """Map a design session_id to a LangGraph thread_id."""
    return f"session:{session_id}"


def thread_id_to_session_id(thread_id: str) -> str:
    """Reverse of session_to_thread_id; strips the 'session:' prefix."""
    return thread_id.removeprefix("session:")


def build_persistent_graph(db_path: str | Path | None = None):
    """Build the LangGraph pipeline graph with a SqliteSaver checkpointer.

    Args:
        db_path: Path to the SQLite file.  Uses the default sessions/
                 directory if not specified.

    Returns:
        Compiled LangGraph graph with durable checkpointing.
    """
    path = get_sessions_db_path() if db_path is None else Path(db_path)
    logger.info("Building persistent graph with checkpointer at %s", path)

    try:
        import sqlite3  # noqa: PLC0415

        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: PLC0415

        # Open a persistent connection (check_same_thread=False for Celery workers)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
    except ImportError:
        # Fallback: langgraph-checkpoint-sqlite not installed; use in-memory
        logger.warning(
            "langgraph-checkpoint-sqlite not installed; falling back to MemorySaver"
        )
        from langgraph.checkpoint.memory import MemorySaver  # noqa: PLC0415

        checkpointer = MemorySaver()

    return build_graph(checkpointer=checkpointer)


def get_graph_state(graph, session_id: str) -> dict | None:
    """Return the current LangGraph state snapshot for a session, or None.

    Args:
        graph:      Compiled LangGraph graph (from build_persistent_graph).
        session_id: Design session identifier.

    Returns:
        State dict snapshot, or None if no checkpoint found.
    """
    config = {"configurable": {"thread_id": session_to_thread_id(session_id)}}
    try:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.values:
            return dict(snapshot.values)
    except Exception:
        pass
    return None


def get_pending_interrupt(graph, session_id: str) -> str | None:
    """Return the name of the node the graph is paused at, or None.

    Returns:
        Node name string (e.g. ``"interview"`` or ``"human_review"``),
        or ``None`` if the graph is not paused.
    """
    config = {"configurable": {"thread_id": session_to_thread_id(session_id)}}
    try:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.next:
            return snapshot.next[0]
    except Exception:
        pass
    return None
