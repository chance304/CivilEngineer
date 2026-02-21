"""
load_project_node — Layer 0.

Loads Project + PlotInfo from the project registry (PostgreSQL).
Falls back gracefully if the DB is unavailable (useful for testing / offline use).

If the project has saved requirements (from a previous session),
those are also loaded into state so the interview can be skipped.

Note on sync/async: LangGraph nodes are called synchronously.
The Celery design task already loads project data before calling the graph,
so state["project"] is usually pre-populated.  This node only queries the
DB if that field is absent (e.g. when running the graph outside Celery).
"""

from __future__ import annotations

import logging

from civilengineer.agent.state import AgentState

logger = logging.getLogger(__name__)


def load_project_node(state: AgentState) -> dict:
    """Load project metadata and plot info into state.

    If ``state["project"]`` is already populated (pre-filled by the Celery
    design job before invoking the graph), this node is a no-op.

    Otherwise it attempts a synchronous DB query using psycopg2 + SQLAlchemy
    (the ``DATABASE_URL_SYNC`` setting must be configured).
    """
    project_id = state.get("project_id", "")

    # Fast path: project was pre-populated by the caller (normal Celery flow)
    if state.get("project"):
        logger.info("load_project_node: project already in state, skipping DB load.")
        return {}

    # Attempt DB load via sync SQLAlchemy
    project_dict, plot_info_dict, requirements_dict = _load_from_db(project_id)

    result: dict = {}
    if project_dict:
        result["project"] = project_dict
        logger.info("Loaded project %s from DB", project_id)
    else:
        logger.warning("Project %s not found in DB; using empty state", project_id)
        result["project"] = {"project_id": project_id, "status": "draft"}

    if plot_info_dict:
        result["plot_info"] = plot_info_dict
    if requirements_dict:
        result["requirements"] = requirements_dict

    return result


def _load_from_db(
    project_id: str,
) -> tuple[dict | None, dict | None, dict | None]:
    """Attempt to load project from the sync PostgreSQL DB.

    Returns:
        (project_dict, plot_info_dict, requirements_dict) — any may be None.
    """
    try:
        from sqlalchemy import create_engine  # noqa: PLC0415
        from sqlmodel import Session, select  # noqa: PLC0415

        from civilengineer.core.config import get_settings  # noqa: PLC0415
        from civilengineer.db.models import ProjectModel  # noqa: PLC0415

        settings = get_settings()
        engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)

        with Session(engine) as session:
            result = session.execute(
                select(ProjectModel).where(ProjectModel.project_id == project_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None, None, None

            project_dict = {
                "project_id": row.project_id,
                "firm_id": row.firm_id,
                "name": row.name,
                "client_name": row.client_name,
                "site_city": row.site_city,
                "site_country": row.site_country,
                "status": row.status,
                "properties": row.properties or {},
            }
            return project_dict, row.plot_info, row.requirements

    except Exception as exc:
        logger.warning(
            "load_project_node: DB query failed for project %s: %s", project_id, exc
        )
        return None, None, None
