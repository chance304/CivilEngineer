"""
Design pipeline router — start and manage design jobs.

All endpoints filter by firm_id from the JWT (multi-tenant).
Engineers must own or be assigned to the project.

Endpoints
---------
POST   /projects/{project_id}/design                     Start a new design job
GET    /projects/{project_id}/design                     List all jobs for project
GET    /projects/{project_id}/design/{session_id}        Get job status
POST   /projects/{project_id}/design/{session_id}/interview   Submit interview answer
POST   /projects/{project_id}/design/{session_id}/approve     Approve floor plan
DELETE /projects/{project_id}/design/{session_id}        Cancel a job
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.db.models import DesignJobModel, ProjectModel
from civilengineer.db.session import get_session
from civilengineer.jobs.design_job import make_job_id
from civilengineer.schemas.auth import User, UserRole
from civilengineer.schemas.jobs import ApprovalResponse, DesignJob, JobStatus

router = APIRouter(tags=["design"])

# --------------------------------------------------------------------------- #
# Request / Response bodies                                                    #
# --------------------------------------------------------------------------- #


class StartDesignRequest(BaseModel):
    """Optional body when starting a new design job."""
    requirements_override: dict | None = None    # Skip interview if provided
    output_dir: str | None = None                # Custom output directory


class InterviewReplyRequest(BaseModel):
    """Engineer's free-text answer to the interview prompt."""
    reply: str


class DesignJobSummary(BaseModel):
    """Lightweight job listing item."""
    job_id: str
    session_id: str
    status: JobStatus
    current_step: str
    submitted_at: datetime
    completed_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/design",
    response_model=DesignJob,
    status_code=status.HTTP_201_CREATED,
)
async def start_design(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_session)],
    body: StartDesignRequest | None = None,
) -> DesignJob:
    """Submit a new design pipeline job for the project.

    Returns immediately with a ``job_id`` and ``session_id`` the client can
    poll or subscribe to via WebSocket.
    """
    project = await _get_project_or_404(project_id, current_user, db)

    if project.status not in ("ready", "completed", "in_progress"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Project is in status '{project.status}'. "
                "Upload and analyze a plot file first (status must be 'ready')."
            ),
        )

    now        = datetime.now(UTC)
    job_id     = make_job_id()
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # Persist the job record
    job_row = DesignJobModel(
        job_id=job_id,
        celery_task_id="",          # Filled after task submission
        project_id=project_id,
        firm_id=current_user.firm_id,
        session_id=session_id,
        submitted_by=current_user.user_id,
        submitted_at=now,
        status="pending",
        current_step="loading",
    )
    db.add(job_row)
    await db.flush()

    # Determine if interview can be skipped
    requirements = body.requirements_override if body else None
    if requirements is None:
        requirements = project.requirements  # May be None → interview will run

    # Submit Celery task
    from civilengineer.jobs.design_job import run_design_pipeline  # noqa: PLC0415

    task = run_design_pipeline.apply_async(
        kwargs={
            "job_id":     job_id,
            "project_id": project_id,
            "session_id": session_id,
            "firm_id":    current_user.firm_id,
            "user_id":    current_user.user_id,
            "resume_value": None,
        }
    )

    # Store Celery task ID
    job_row.celery_task_id = task.id
    db.add(job_row)

    # Update project status to in_progress
    project.status = "in_progress"
    project.updated_at = now
    db.add(project)

    return _row_to_schema(job_row)


@router.get(
    "/projects/{project_id}/design",
    response_model=list[DesignJobSummary],
)
async def list_design_jobs(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[DesignJobSummary]:
    """List all design jobs for a project, most recent first."""
    await _get_project_or_404(project_id, current_user, db)

    result = await db.execute(
        select(DesignJobModel)
        .where(
            DesignJobModel.project_id == project_id,
            DesignJobModel.firm_id == current_user.firm_id,
        )
        .order_by(DesignJobModel.submitted_at.desc())
    )
    rows = result.scalars().all()
    return [
        DesignJobSummary(
            job_id=r.job_id,
            session_id=r.session_id,
            status=JobStatus(r.status),
            current_step=r.current_step,
            submitted_at=r.submitted_at,
            completed_at=r.completed_at,
        )
        for r in rows
    ]


@router.get(
    "/projects/{project_id}/design/{session_id}",
    response_model=DesignJob,
)
async def get_design_job(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DesignJob:
    """Get the current status and result of a design job."""
    job = await _get_job_or_404(project_id, session_id, current_user, db)
    return _row_to_schema(job)


@router.post(
    "/projects/{project_id}/design/{session_id}/interview",
    response_model=DesignJob,
)
async def submit_interview_reply(
    project_id: str,
    session_id: str,
    body: InterviewReplyRequest,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DesignJob:
    """Submit the engineer's interview answer to resume the paused pipeline.

    The job must be in ``paused`` status and the interrupt must be at the
    ``interview`` node.
    """
    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job is not paused (current status: '{job.status}').",
        )
    if job.current_step not in ("interview", "loading"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job is paused at '{job.current_step}', not at 'interview'.",
        )

    # Reset to pending and re-submit with resume_value
    job.status = "pending"
    job.current_step = "loading"
    db.add(job)
    await db.flush()

    from civilengineer.jobs.design_job import run_design_pipeline  # noqa: PLC0415

    task = run_design_pipeline.apply_async(
        kwargs={
            "job_id":        job.job_id,
            "project_id":    project_id,
            "session_id":    session_id,
            "firm_id":       current_user.firm_id,
            "user_id":       current_user.user_id,
            "resume_value":  body.reply,
        }
    )
    job.celery_task_id = task.id
    db.add(job)

    return _row_to_schema(job)


@router.post(
    "/projects/{project_id}/design/{session_id}/approve",
    response_model=DesignJob,
)
async def approve_floor_plan(
    project_id: str,
    session_id: str,
    body: ApprovalResponse,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DesignJob:
    """Approve (or reject) the floor plan generated by the design pipeline.

    If ``approved=True`` the pipeline continues to the drawing phase.
    If ``approved=False`` the job is re-submitted with a "revise" command.
    """
    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job is not paused (current status: '{job.status}').",
        )
    if job.current_step != "human_review":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job is paused at '{job.current_step}', not at 'human_review'.",
        )

    if body.approved:
        resume_value = "approved"
    else:
        feedback = body.feedback or ""
        resume_value = f"revise:{feedback}"

    job.status = "pending"
    job.current_step = "loading"
    db.add(job)
    await db.flush()

    from civilengineer.jobs.design_job import run_design_pipeline  # noqa: PLC0415

    task = run_design_pipeline.apply_async(
        kwargs={
            "job_id":       job.job_id,
            "project_id":   project_id,
            "session_id":   session_id,
            "firm_id":      current_user.firm_id,
            "user_id":      current_user.user_id,
            "resume_value": resume_value,
        }
    )
    job.celery_task_id = task.id
    db.add(job)

    return _row_to_schema(job)


@router.delete(
    "/projects/{project_id}/design/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_design_job(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Cancel a pending or paused design job.

    Completed jobs cannot be cancelled.
    """
    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot cancel a job in status '{job.status}'.",
        )

    # Revoke Celery task if still pending
    if job.celery_task_id:
        try:
            from civilengineer.jobs.celery_app import celery_app  # noqa: PLC0415

            celery_app.control.revoke(job.celery_task_id, terminate=False)
        except Exception:
            pass

    job.status = "cancelled"
    job.completed_at = datetime.now(UTC)
    db.add(job)


# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #


def _row_to_schema(row: DesignJobModel) -> DesignJob:
    return DesignJob(
        job_id=row.job_id,
        celery_task_id=row.celery_task_id,
        project_id=row.project_id,
        session_id=row.session_id,
        firm_id=row.firm_id,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        status=JobStatus(row.status),
        current_step=row.current_step,  # type: ignore[arg-type]
        result=row.result,
        error=row.error,
    )


async def _get_project_or_404(
    project_id: str,
    current_user: User,
    db: AsyncSession,
) -> ProjectModel:
    result = await db.execute(
        select(ProjectModel).where(
            ProjectModel.project_id == project_id,
            ProjectModel.firm_id == current_user.firm_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if current_user.role == UserRole.ENGINEER and row.created_by != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    return row


async def _get_job_or_404(
    project_id: str,
    session_id: str,
    current_user: User,
    db: AsyncSession,
) -> DesignJobModel:
    result = await db.execute(
        select(DesignJobModel).where(
            DesignJobModel.project_id == project_id,
            DesignJobModel.session_id == session_id,
            DesignJobModel.firm_id == current_user.firm_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Design job not found.")
    return row
