"""
Plot upload and analysis API.

Upload flow:
  1. GET /projects/{id}/plot/upload-url
       → presigned S3 PUT URL + storage_key
  2. Client uploads DXF/DWG directly to S3/MinIO (no API proxy)
  3. POST /projects/{id}/plot  body: {storage_key, filename}
       → updates project status → "plot_pending"
       → queues Celery analyse_plot task
       → returns {job_id, status: "pending"}
  4. GET /projects/{id}/plot
       → returns PlotInfo once analysis is complete
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.core.config import get_settings
from civilengineer.db.models import ProjectModel
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import User
from civilengineer.schemas.project import PlotInfo
from civilengineer.storage.s3_backend import generate_presigned_upload_url

router = APIRouter(prefix="/projects", tags=["plots"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class PlotUploadUrlResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_in: int = 3600


class PlotNotifyRequest(BaseModel):
    storage_key: str
    filename: str


class PlotNotifyResponse(BaseModel):
    job_id: str
    status: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _get_project_or_404(
    project_id: str,
    firm_id: str,
    session,
) -> ProjectModel:
    result = await session.execute(
        select(ProjectModel).where(
            ProjectModel.project_id == project_id,
            ProjectModel.firm_id == firm_id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{project_id}/plot/upload-url", response_model=PlotUploadUrlResponse)
async def get_plot_upload_url(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    session=Depends(get_session),
) -> PlotUploadUrlResponse:
    """
    Return a presigned S3 PUT URL so the client can upload the plot DXF/DWG
    directly to MinIO/S3 without streaming through the API server.
    """
    await _get_project_or_404(project_id, current_user.firm_id, session)

    storage_key = (
        f"{current_user.firm_id}/{project_id}/plot/{uuid.uuid4().hex}.dxf"
    )
    upload_url = generate_presigned_upload_url(
        bucket=settings.S3_BUCKET_PROJECTS,
        key=storage_key,
        content_type="application/octet-stream",
    )
    return PlotUploadUrlResponse(upload_url=upload_url, storage_key=storage_key)


@router.post(
    "/{project_id}/plot",
    response_model=PlotNotifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def notify_plot_uploaded(
    project_id: str,
    body: PlotNotifyRequest,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    session=Depends(get_session),
) -> PlotNotifyResponse:
    """
    Notify the server that the client has finished uploading the plot file.
    Queues an async Celery job to download and analyse the DXF.
    """
    project = await _get_project_or_404(project_id, current_user.firm_id, session)

    # Mark project as analysis-in-progress
    project.status = "plot_pending"
    project.updated_at = datetime.now(UTC)
    session.add(project)
    # session will be committed by get_session context manager

    # Lazy import to avoid pulling Celery into tests that don't need it
    from civilengineer.jobs.plot_job import analyze_plot  # noqa: PLC0415

    task = analyze_plot.delay(
        project_id=project_id,
        storage_key=body.storage_key,
        firm_id=current_user.firm_id,
        user_id=current_user.user_id,
    )

    return PlotNotifyResponse(job_id=task.id, status="pending")


@router.get("/{project_id}/plot", response_model=PlotInfo)
async def get_plot_info(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session=Depends(get_session),
) -> PlotInfo:
    """Return the analysed PlotInfo for a project (404 until analysis completes)."""
    project = await _get_project_or_404(project_id, current_user.firm_id, session)

    if project.plot_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot analysis has not completed yet.",
        )

    return PlotInfo.model_validate(project.plot_info)
