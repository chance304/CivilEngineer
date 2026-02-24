"""
Design pipeline router — start and manage design jobs.

All endpoints filter by firm_id from the JWT (multi-tenant).
Engineers must own or be assigned to the project.

Endpoints
---------
POST   /projects/{project_id}/design                                Start a new design job
GET    /projects/{project_id}/design                                List all jobs for project
GET    /projects/{project_id}/design/{session_id}                   Get job status
POST   /projects/{project_id}/design/{session_id}/interview         Submit interview answer
POST   /projects/{project_id}/design/{session_id}/approve           Approve floor plan (engineer)
DELETE /projects/{project_id}/design/{session_id}                   Cancel a job
GET    /projects/{project_id}/design/{session_id}/files             List output files (presigned URLs)
GET    /projects/{project_id}/design/{session_id}/files/zip         Download all files as ZIP
POST   /projects/{project_id}/design/{session_id}/finalize          Documentation completeness gate
GET    /projects/{project_id}/design/{session_id}/client-approval   Get client approval status
POST   /projects/{project_id}/design/{session_id}/client-approve    Submit client sign-off
"""

from __future__ import annotations

import io
import logging
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

logger = logging.getLogger(__name__)

from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.db.models import ClientApprovalModel, DesignJobModel, ProjectModel
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


class OutputFileResponse(BaseModel):
    """A single output file with a short-lived presigned download URL."""
    name: str
    type: str       # dxf_floor_plan | dxf_elevation | dxf_3d | dxf_mep | pdf | ifc | dwg
    download_url: str
    size_bytes: int


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


@router.get(
    "/projects/{project_id}/design/{session_id}/files",
    response_model=list[OutputFileResponse],
)
async def get_design_files(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[OutputFileResponse]:
    """Return output files for a completed design session with fresh presigned download URLs."""
    from civilengineer.core.config import get_settings  # noqa: PLC0415
    from civilengineer.storage import s3_backend  # noqa: PLC0415

    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status != "completed":
        return []

    records = (job.result or {}).get("output_file_records") or []
    settings = get_settings()
    files: list[OutputFileResponse] = []
    for rec in records:
        try:
            url = s3_backend.generate_presigned_download_url(
                settings.S3_BUCKET_PROJECTS,
                rec["s3_key"],
                expiry=3600,
            )
            files.append(OutputFileResponse(
                name=rec["name"],
                type=rec["type"],
                download_url=url,
                size_bytes=rec["size_bytes"],
            ))
        except Exception as exc:
            logger.warning("get_design_files: presign failed for %s: %s", rec.get("s3_key"), exc)

    return files


@router.get(
    "/projects/{project_id}/design/{session_id}/files/zip",
)
async def download_design_files_zip(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Download all output files for a design session bundled as a ZIP archive."""
    from civilengineer.core.config import get_settings  # noqa: PLC0415
    from civilengineer.storage import s3_backend  # noqa: PLC0415

    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed output files for this session.",
        )

    records = (job.result or {}).get("output_file_records") or []
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No output files found for this session.",
        )

    settings = get_settings()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rec in records:
            try:
                data = s3_backend.download_bytes(settings.S3_BUCKET_PROJECTS, rec["s3_key"])
                zf.writestr(rec["name"], data)
            except Exception as exc:
                logger.warning(
                    "download_design_files_zip: could not include %s: %s",
                    rec.get("name"), exc,
                )

    buf.seek(0)
    short_id = session_id[:8] if len(session_id) >= 8 else session_id
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="design-{short_id}.zip"',
        },
    )


class FinalizeResponse(BaseModel):
    """Result of the documentation completeness check + finalization."""
    job_id: str
    session_id: str
    finalized: bool
    finalized_at: datetime | None = None
    completeness: dict          # Output of _check_documentation_completeness()


@router.post(
    "/projects/{project_id}/design/{session_id}/finalize",
    response_model=FinalizeResponse,
)
async def finalize_design_session(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FinalizeResponse:
    """Run the documentation completeness gate and mark the session as finalized.

    Required output files (must all be present):
      - At least one floor plan DXF
      - A site plan DXF
      - At least one PDF package

    Advisory items are reported but do not block finalization.

    Returns 422 if required files are missing.
    Returns 200 immediately if already finalized.
    """
    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status == "finalized":
        records = (job.result or {}).get("output_file_records") or []
        return FinalizeResponse(
            job_id=job.job_id,
            session_id=job.session_id,
            finalized=True,
            finalized_at=job.finalized_at,
            completeness=_check_documentation_completeness(records),
        )

    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Session must be in 'completed' status to finalize (current: '{job.status}').",
        )

    records = (job.result or {}).get("output_file_records") or []
    report = _check_documentation_completeness(records)

    if not report["is_complete"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Documentation completeness check failed. Missing required files.",
                "missing_required": report["missing_required"],
                "missing_advisory": report["missing_advisory"],
                "present": report["present"],
            },
        )

    now = datetime.now(UTC)
    job.status = "finalized"
    job.finalized_at = now
    db.add(job)

    logger.info(
        "Session %s finalized by user %s. Advisory items missing: %s",
        session_id, current_user.user_id, report["missing_advisory"],
    )

    return FinalizeResponse(
        job_id=job.job_id,
        session_id=job.session_id,
        finalized=True,
        finalized_at=now,
        completeness=report,
    )


# --------------------------------------------------------------------------- #
# Client approval endpoints (viewer-accessible)                               #
# --------------------------------------------------------------------------- #


class ClientApproveRequest(BaseModel):
    """Client decision on the finalized design."""
    action: str        # "approved" | "revision_requested"
    notes: str = ""    # Required when action == "revision_requested"


class ClientApprovalResponse(BaseModel):
    """Current client sign-off status for a design session."""
    session_id: str
    has_approval: bool
    action: str | None = None          # "approved" | "revision_requested"
    notes: str | None = None
    submitted_by: str | None = None    # user_id
    submitted_at: datetime | None = None


@router.get(
    "/projects/{project_id}/design/{session_id}/client-approval",
    response_model=ClientApprovalResponse,
)
async def get_client_approval(
    project_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.DESIGN_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ClientApprovalResponse:
    """Return the most recent client sign-off for a design session (if any).

    Accessible to all roles (including viewer).
    Returns has_approval=False when no client sign-off has been submitted yet.
    """
    await _get_job_or_404(project_id, session_id, current_user, db)

    result = await db.execute(
        select(ClientApprovalModel)
        .where(
            ClientApprovalModel.session_id == session_id,
            ClientApprovalModel.firm_id == current_user.firm_id,
        )
        .order_by(ClientApprovalModel.submitted_at.desc())
    )
    row = result.scalars().first()

    if row is None:
        return ClientApprovalResponse(session_id=session_id, has_approval=False)

    return ClientApprovalResponse(
        session_id=session_id,
        has_approval=True,
        action=row.action,
        notes=row.notes or None,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
    )


@router.post(
    "/projects/{project_id}/design/{session_id}/client-approve",
    response_model=ClientApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_client_approval(
    project_id: str,
    session_id: str,
    body: ClientApproveRequest,
    current_user: Annotated[User, Depends(require_permission(Permission.DESIGN_READ))],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ClientApprovalResponse:
    """Submit a client sign-off decision for a completed or finalized design session.

    Accessible to all roles (viewer = client representative).
    Multiple submissions are allowed — each creates a new record; the GET endpoint
    returns the most recent one.

    action values:
      - ``approved``             — client accepts the design for construction
      - ``revision_requested``   — client asks for changes (notes required)
    """
    if body.action not in ("approved", "revision_requested"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="action must be 'approved' or 'revision_requested'.",
        )
    if body.action == "revision_requested" and not body.notes.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="notes are required when requesting a revision.",
        )

    job = await _get_job_or_404(project_id, session_id, current_user, db)

    if job.status not in ("completed", "finalized"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Client approval is only available for completed or finalized sessions "
                f"(current status: '{job.status}')."
            ),
        )

    now = datetime.now(UTC)
    record = ClientApprovalModel(
        project_id=project_id,
        session_id=session_id,
        firm_id=current_user.firm_id,
        submitted_by=current_user.user_id,
        submitted_at=now,
        action=body.action,
        notes=body.notes.strip(),
    )
    db.add(record)
    await db.flush()

    logger.info(
        "Client approval submitted: session=%s action=%s user=%s",
        session_id, body.action, current_user.user_id,
    )

    return ClientApprovalResponse(
        session_id=session_id,
        has_approval=True,
        action=record.action,
        notes=record.notes or None,
        submitted_by=record.submitted_by,
        submitted_at=record.submitted_at,
    )


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
        finalized_at=row.finalized_at,
        status=JobStatus(row.status),
        current_step=row.current_step,  # type: ignore[arg-type]
        result=row.result,
        error=row.error,
    )


def _check_documentation_completeness(records: list[dict]) -> dict:
    """Check which required output files are present.

    Required for finalization:
      - At least one floor plan DXF
      - A site plan DXF (file named site_plan.dxf)
      - At least one PDF package

    Advisory (reported but do not block finalization — not yet generated by pipeline):
      - Elevation DXFs (front/rear/left/right)
      - 3D building outline DXF
      - MEP schematic DXF

    Returns a completeness report dict.
    """
    types = {r["type"] for r in records}
    names = {r["name"] for r in records}

    has_floor_plan = "dxf_floor_plan" in types
    has_pdf        = "pdf" in types
    has_site_plan  = any("site_plan" in n for n in names)
    has_elevation  = "dxf_elevation" in types
    has_3d         = "dxf_3d" in types
    has_mep        = "dxf_mep" in types

    missing_required: list[str] = []
    if not has_floor_plan:
        missing_required.append("floor plan DXF")
    if not has_pdf:
        missing_required.append("PDF package")
    if not has_site_plan:
        missing_required.append("site plan DXF (site_plan.dxf)")

    missing_advisory: list[str] = []
    if not has_elevation:
        missing_advisory.append("elevation DXFs (front / rear / left / right)")
    if not has_3d:
        missing_advisory.append("3D building outline DXF")
    if not has_mep:
        missing_advisory.append("MEP schematic DXF")

    return {
        "is_complete": len(missing_required) == 0,
        "missing_required": missing_required,
        "missing_advisory": missing_advisory,
        "present": {
            "floor_plan_dxf": has_floor_plan,
            "site_plan_dxf":  has_site_plan,
            "pdf":            has_pdf,
            "elevation_dxf":  has_elevation,
            "dxf_3d":         has_3d,
            "mep_dxf":        has_mep,
        },
        "total_files": len(records),
    }


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
