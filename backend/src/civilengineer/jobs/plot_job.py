"""
Celery task: analyse a plot DXF file.

Flow:
  1. Download DXF bytes from S3/MinIO
  2. Run the plot analyser → PlotInfo
  3. Persist PlotInfo to ProjectModel.plot_info (JSON column)
  4. Update project status:  confidence ≥ 0.5 → "ready",  else → "draft"
  5. Publish a Redis pub/sub event on channel  project:{project_id}:events
     so WebSocket listeners can forward it to the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging

from civilengineer.jobs.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="civilengineer.jobs.plot_job.analyze_plot",
    max_retries=3,
    default_retry_delay=30,
)
def analyze_plot(
    self,
    project_id: str,
    storage_key: str,
    firm_id: str,
    user_id: str,
) -> dict:
    """
    Celery task entry point (sync wrapper around async logic).
    """
    try:
        return asyncio.run(
            _analyze_plot_async(
                project_id=project_id,
                storage_key=storage_key,
                firm_id=firm_id,
                user_id=user_id,
            )
        )
    except Exception as exc:
        logger.exception("analyze_plot failed for project %s: %s", project_id, exc)
        raise self.retry(exc=exc)


async def _analyze_plot_async(
    project_id: str,
    storage_key: str,
    firm_id: str,
    user_id: str,
) -> dict:
    """Async implementation — runs inside asyncio.run() from the Celery worker."""
    import redis.asyncio as aioredis
    from sqlmodel import select

    from civilengineer.core.config import get_settings
    from civilengineer.db.models import ProjectModel
    from civilengineer.db.session import AsyncSessionLocal
    from civilengineer.plot_analyzer.dwg_reader import analyze_dxf_bytes
    from civilengineer.storage.s3_backend import download_bytes

    settings = get_settings()

    # ------------------------------------------------------------------
    # 1. Download file from S3
    # ------------------------------------------------------------------
    logger.info("Downloading plot file: bucket=%s key=%s", settings.S3_BUCKET_PROJECTS, storage_key)
    data = download_bytes(settings.S3_BUCKET_PROJECTS, storage_key)

    # ------------------------------------------------------------------
    # 2. Run plot analyser
    # ------------------------------------------------------------------
    logger.info("Analysing plot for project %s", project_id)
    plot_info = analyze_dxf_bytes(data, storage_key=storage_key)
    logger.info(
        "Analysis complete: confidence=%.2f area=%.1f sqm",
        plot_info.extraction_confidence,
        plot_info.area_sqm,
    )

    # ------------------------------------------------------------------
    # 3. Persist to DB
    # ------------------------------------------------------------------
    new_status = "ready" if plot_info.extraction_confidence >= 0.5 else "draft"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProjectModel).where(ProjectModel.project_id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise ValueError(f"Project {project_id} not found in DB")

        project.plot_info = plot_info.model_dump()
        project.status = new_status
        await session.commit()

    logger.info("Project %s updated: status=%s", project_id, new_status)

    # ------------------------------------------------------------------
    # 4. Publish WebSocket event via Redis pub/sub
    # ------------------------------------------------------------------
    event = json.dumps({
        "type": "plot.analyzed",
        "project_id": project_id,
        "status": new_status,
        "confidence": plot_info.extraction_confidence,
        "area_sqm": plot_info.area_sqm,
        "width_m": plot_info.width_m,
        "depth_m": plot_info.depth_m,
        "facing": plot_info.facing,
        "is_rectangular": plot_info.is_rectangular,
        "notes": plot_info.extraction_notes,
    })
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.publish(f"project:{project_id}:events", event)
    finally:
        await r.aclose()

    return {"status": "success", "confidence": plot_info.extraction_confidence}
