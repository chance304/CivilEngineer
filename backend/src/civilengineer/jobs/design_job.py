"""
Celery task: run the full LangGraph design pipeline for a project.

Flow (first invocation)
-----------------------
  1. Load project + plot_info from DB → pre-populate AgentState
  2. Build LangGraph graph with SqliteSaver checkpointer
  3. Invoke graph; it may pause at "interview" or "human_review" interrupts
  4. If paused  → update DesignJobModel status = "paused", publish WS event
  5. If finished → update DesignJobModel status = "completed", publish WS event
  6. On error   → update DesignJobModel status = "failed", publish WS event

Flow (resume invocation after engineer input)
---------------------------------------------
  1. Load current graph state from checkpointer
  2. Resume with Command(resume=engineer_input)
  3. Continue steps 4–6 as above
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from civilengineer.jobs.celery_app import celery_app

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Celery task entry point                                                      #
# --------------------------------------------------------------------------- #


@celery_app.task(
    bind=True,
    name="civilengineer.jobs.design_job.run_design_pipeline",
    max_retries=0,          # Design jobs are not auto-retried (human in the loop)
    acks_late=True,         # Only ack after task completes / is paused
    track_started=True,
)
def run_design_pipeline(
    self,
    job_id: str,
    project_id: str,
    session_id: str,
    firm_id: str,
    user_id: str,
    resume_value: str | None = None,
) -> dict:
    """
    Celery task: run or resume the LangGraph design pipeline.

    Args:
        job_id:       DesignJobModel primary key.
        project_id:   Project being designed.
        session_id:   Unique session / LangGraph thread ID.
        firm_id:      Multi-tenant isolation key.
        user_id:      Engineer who submitted the job.
        resume_value: If resuming after an interrupt, the engineer's reply
                      (e.g. "3BHK, 2 floors, modern" or "approved").

    Returns:
        Result dict with ``status``, ``interrupted_at``, and ``output_files``.
    """
    return asyncio.run(
        _run_design_pipeline_async(
            task_self=self,
            job_id=job_id,
            project_id=project_id,
            session_id=session_id,
            firm_id=firm_id,
            user_id=user_id,
            resume_value=resume_value,
        )
    )


# --------------------------------------------------------------------------- #
# Async implementation                                                         #
# --------------------------------------------------------------------------- #


async def _run_design_pipeline_async(
    task_self,
    job_id: str,
    project_id: str,
    session_id: str,
    firm_id: str,
    user_id: str,
    resume_value: str | None,
) -> dict:
    """Async body — runs inside asyncio.run() from the Celery worker."""
    from langgraph.types import Command  # noqa: PLC0415

    from civilengineer.agent.session_store import (  # noqa: PLC0415
        build_persistent_graph,
        session_to_thread_id,
    )
    from civilengineer.agent.state import make_initial_state  # noqa: PLC0415

    now = datetime.now(UTC)

    # ------------------------------------------------------------------ #
    # 1. Mark job as RUNNING in DB                                        #
    # ------------------------------------------------------------------ #
    await _update_job_db(job_id, status="running", current_step="loading", started_at=now)
    await _publish_event(project_id, {
        "type": "design.progress",
        "job_id": job_id,
        "session_id": session_id,
        "status": "running",
        "current_step": "loading",
        "step_message": "Loading project data…",
        "progress_pct": 5,
    })

    try:
        # ------------------------------------------------------------------ #
        # 2. Load project from DB (pre-populate initial state)               #
        # ------------------------------------------------------------------ #
        project_dict, plot_info_dict, requirements_dict = await _load_project_async(project_id)

        # ------------------------------------------------------------------ #
        # 3. Build graph                                                      #
        # ------------------------------------------------------------------ #
        graph = build_persistent_graph()
        thread_id = session_to_thread_id(session_id)
        config = {"configurable": {"thread_id": thread_id}}

        # ------------------------------------------------------------------ #
        # 4. Invoke or resume                                                 #
        # ------------------------------------------------------------------ #
        if resume_value is not None:
            # Resume from interrupt
            logger.info("Resuming session %s with input: %s", session_id, resume_value[:80])
            graph_input = Command(resume=resume_value)
        else:
            # Fresh start — build initial state
            initial = make_initial_state(project_id=project_id, session_id=session_id)
            if project_dict:
                initial["project"] = project_dict
            if plot_info_dict:
                initial["plot_info"] = plot_info_dict
            if requirements_dict:
                initial["requirements"] = requirements_dict
            graph_input = initial

        await _publish_event(project_id, {
            "type": "design.progress",
            "job_id": job_id,
            "session_id": session_id,
            "status": "running",
            "current_step": "planning",
            "step_message": "Pipeline running…",
            "progress_pct": 10,
        })

        # ------------------------------------------------------------------ #
        # 2b. Snapshot requirements at job start (for first invocation)      #
        # ------------------------------------------------------------------ #
        if resume_value is None and requirements_dict:
            await _write_requirements_version(
                job_id=job_id,
                project_id=project_id,
                firm_id=firm_id,
                session_id=session_id,
                requirements=requirements_dict,
            )

        # ------------------------------------------------------------------ #
        # 2c. Record approval decision when resuming from human_review       #
        # ------------------------------------------------------------------ #
        if resume_value is not None:
            await _write_approval_from_resume(
                job_id=job_id,
                project_id=project_id,
                firm_id=firm_id,
                session_id=session_id,
                user_id=user_id,
                resume_value=resume_value,
            )

        # LangGraph invoke — runs synchronously (nodes are sync)
        graph.invoke(graph_input, config=config)

        # ------------------------------------------------------------------ #
        # 5. Check post-invoke state: paused or finished?                    #
        # ------------------------------------------------------------------ #
        snapshot = graph.get_state(config)
        next_nodes = snapshot.next if snapshot else ()

        # Persist accumulated decision events (best-effort)
        await _persist_pipeline_events(
            project_id=project_id,
            job_id=job_id,
            session_id=session_id,
            firm_id=firm_id,
            snapshot_values=snapshot.values if snapshot else {},
        )

        if next_nodes:
            # Interrupted — waiting for human input
            interrupted_at = next_nodes[0]
            logger.info("Session %s paused at node '%s'", session_id, interrupted_at)

            # Build floor-plan summary if available at human_review
            floor_plan_summary = None
            if interrupted_at == "human_review":
                fps = (snapshot.values or {}).get("floor_plans") or []
                floor_plan_summary = _summarise_floor_plans(fps)

            await _update_job_db(
                job_id,
                status="paused",
                current_step=interrupted_at,
                result={
                    "interrupted_at": interrupted_at,
                    "floor_plan_summary": floor_plan_summary,
                },
            )
            await _publish_event(project_id, {
                "type": "design.paused",
                "job_id": job_id,
                "session_id": session_id,
                "status": "paused",
                "interrupted_at": interrupted_at,
                "floor_plan_summary": floor_plan_summary,
            })
            return {
                "status": "paused",
                "interrupted_at": interrupted_at,
                "output_files": [],
            }

        # Graph ran to completion
        final_values = snapshot.values if snapshot else {}
        dxf_paths  = (final_values or {}).get("dxf_paths") or []
        pdf_paths  = (final_values or {}).get("pdf_paths") or []
        output_files = dxf_paths + pdf_paths
        errors     = (final_values or {}).get("errors") or []

        if errors:
            error_msg = "; ".join(str(e) for e in errors)
            logger.error("Session %s completed with errors: %s", session_id, error_msg)
            await _update_job_db(
                job_id, status="failed", current_step="done",
                completed_at=datetime.now(UTC), error=error_msg,
            )
            await _publish_event(project_id, {
                "type": "design.failed",
                "job_id": job_id,
                "session_id": session_id,
                "status": "failed",
                "error": error_msg,
            })
            return {"status": "failed", "error": error_msg, "output_files": output_files}

        logger.info("Session %s completed. Files: %s", session_id, output_files)
        await _update_job_db(
            job_id,
            status="completed",
            current_step="done",
            completed_at=datetime.now(UTC),
            result={"output_files": output_files},
        )
        await _publish_event(project_id, {
            "type": "design.completed",
            "job_id": job_id,
            "session_id": session_id,
            "status": "completed",
            "output_files": output_files,
            "progress_pct": 100,
        })
        return {"status": "completed", "output_files": output_files}

    except Exception as exc:
        msg = f"Design pipeline crashed: {exc}"
        logger.exception("Session %s: %s", session_id, msg)
        await _update_job_db(
            job_id,
            status="failed",
            current_step="done",
            completed_at=datetime.now(UTC),
            error=msg,
        )
        await _publish_event(project_id, {
            "type": "design.failed",
            "job_id": job_id,
            "session_id": session_id,
            "status": "failed",
            "error": msg,
        })
        return {"status": "failed", "error": msg, "output_files": []}


# --------------------------------------------------------------------------- #
# DB helpers                                                                   #
# --------------------------------------------------------------------------- #


async def _load_project_async(project_id: str) -> tuple[dict | None, dict | None, dict | None]:
    """Load project, plot_info, and requirements from the DB.

    Returns:
        (project_dict, plot_info_dict, requirements_dict) — any may be None.
    """
    try:
        from sqlmodel import select  # noqa: PLC0415

        from civilengineer.db.models import ProjectModel  # noqa: PLC0415
        from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            result = await session.execute(
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
        logger.warning("Could not load project %s from DB: %s", project_id, exc)
        return None, None, None


async def _update_job_db(
    job_id: str,
    status: str,
    current_step: str,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Update DesignJobModel fields in the DB."""
    try:
        from sqlmodel import select  # noqa: PLC0415

        from civilengineer.db.models import DesignJobModel  # noqa: PLC0415
        from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(DesignJobModel).where(DesignJobModel.job_id == job_id)
            )
            job = res.scalar_one_or_none()
            if job is None:
                logger.error("_update_job_db: job %s not found", job_id)
                return

            job.status = status
            job.current_step = current_step
            if started_at is not None:
                job.started_at = started_at
            if completed_at is not None:
                job.completed_at = completed_at
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

            session.add(job)
            await session.commit()
    except Exception as exc:
        logger.warning("_update_job_db failed for job %s: %s", job_id, exc)


async def _publish_event(project_id: str, event: dict) -> None:
    """Publish a JSON event on the Redis pub/sub channel for the project."""
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415

        from civilengineer.core.config import get_settings  # noqa: PLC0415

        settings = get_settings()
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await r.publish(f"project:{project_id}:events", json.dumps(event))
        finally:
            await r.aclose()
    except Exception as exc:
        logger.debug("Could not publish WS event: %s", exc)


# --------------------------------------------------------------------------- #
# Utility                                                                      #
# --------------------------------------------------------------------------- #


def _summarise_floor_plans(floor_plan_dicts: list[dict]) -> dict:
    """Build a lightweight summary of floor plans for the approval request."""
    total_area = 0.0
    total_rooms = 0
    floors = []
    for fp in floor_plan_dicts:
        rooms = fp.get("rooms") or []
        floor_area = sum(r.get("area_sqm", 0) for r in rooms)
        total_area += floor_area
        total_rooms += len(rooms)
        floors.append({
            "floor": fp.get("floor", 1),
            "num_rooms": len(rooms),
            "area_sqm": round(floor_area, 2),
            "rooms": [
                {"type": r.get("room_type", ""), "area_sqm": round(r.get("area_sqm", 0), 2)}
                for r in rooms
            ],
        })
    return {
        "total_area_sqm": round(total_area, 2),
        "total_rooms": total_rooms,
        "num_floors": len(floors),
        "floors": floors,
    }


def make_job_id() -> str:
    """Generate a unique design job ID."""
    return f"job_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Decision-tracking helpers                                                    #
# --------------------------------------------------------------------------- #


async def _write_requirements_version(
    job_id: str,
    project_id: str,
    firm_id: str,
    session_id: str,
    requirements: dict,
) -> None:
    """Snapshot requirements at the start of a fresh job run."""
    try:
        from civilengineer.db.repositories.decisions_repository import (  # noqa: PLC0415
            write_requirements_version,
        )
        from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            await write_requirements_version(
                session,
                project_id=project_id,
                firm_id=firm_id,
                job_id=job_id,
                session_id=session_id,
                requirements=requirements,
            )
            await session.commit()
    except Exception as exc:
        logger.warning("_write_requirements_version failed for job %s: %s", job_id, exc)


async def _write_approval_from_resume(
    job_id: str,
    project_id: str,
    firm_id: str,
    session_id: str,
    user_id: str,
    resume_value: str,
) -> None:
    """Record engineer's interrupt decision when resuming from human_review."""
    try:
        from civilengineer.db.repositories.decisions_repository import (  # noqa: PLC0415
            write_design_approval,
        )
        from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

        resume_lower = resume_value.strip().lower()
        if any(w in resume_lower for w in ("approve", "yes", "ok", "good", "looks")):
            decision = "approve"
        elif any(w in resume_lower for w in ("revise", "change", "no", "modify", "redo")):
            decision = "revise"
        elif any(w in resume_lower for w in ("abort", "cancel", "stop")):
            decision = "abort"
        else:
            decision = "approve"  # default: treat unknown as approve

        async with AsyncSessionLocal() as session:
            await write_design_approval(
                session,
                project_id=project_id,
                firm_id=firm_id,
                job_id=job_id,
                session_id=session_id,
                approved_by=user_id,
                decision=decision,
                feedback_text=resume_value[:1000],
                approval_type="floor_plan",
            )
            await session.commit()
    except Exception as exc:
        logger.warning("_write_approval_from_resume failed for job %s: %s", job_id, exc)


async def _persist_pipeline_events(
    project_id: str,
    job_id: str,
    session_id: str,
    firm_id: str,
    snapshot_values: dict,
) -> None:
    """Persist accumulated decision_events from the graph snapshot to the DB."""
    try:
        events = (snapshot_values or {}).get("decision_events") or []
        if not events:
            return

        from civilengineer.db.repositories.decisions_repository import (  # noqa: PLC0415
            persist_decision_events,
        )
        from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

        async with AsyncSessionLocal() as session:
            await persist_decision_events(
                session,
                events=events,
                project_id=project_id,
                job_id=job_id,
                session_id=session_id,
                firm_id=firm_id,
            )
            await session.commit()
        logger.debug(
            "_persist_pipeline_events: persisted %d events for job=%s", len(events), job_id
        )
    except Exception as exc:
        logger.warning("_persist_pipeline_events failed for job %s: %s", job_id, exc)
