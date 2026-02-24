"""
Async design job schemas.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class JobStatus(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    PAUSED    = "paused"      # Waiting for human approval
    COMPLETED = "completed"
    FINALIZED = "finalized"   # Completed + documentation completeness verified
    FAILED    = "failed"
    CANCELLED = "cancelled"


class DesignJobStep(StrEnum):
    LOADING           = "loading"
    INTERVIEWING      = "interviewing"
    VALIDATING        = "validating"
    PLANNING          = "planning"
    SOLVING           = "solving"
    GEOMETRY          = "geometry"
    ELEVATION         = "elevation"          # Generating elevation + 3D views
    AWAITING_APPROVAL = "awaiting_approval"  # Human-in-the-loop pause
    DRAWING           = "drawing"
    VERIFYING         = "verifying"
    SAVING            = "saving"
    DONE              = "done"


class JobProgress(BaseModel):
    """
    Real-time progress update sent over WebSocket.
    Event type: "design.progress"
    """
    job_id: str
    project_id: str
    session_id: str
    status: JobStatus
    current_step: DesignJobStep
    step_message: str        # "Running constraint solver..."
    progress_pct: int        # 0–100
    solver_iteration: int | None = None
    constraint_relaxed: str | None = None
    error: str | None = None
    floor_plan_summary: dict | None = None  # Set when step = AWAITING_APPROVAL


class DesignJob(BaseModel):
    """Celery job record as stored in PostgreSQL."""
    job_id: str
    celery_task_id: str
    project_id: str
    session_id: str
    firm_id: str
    submitted_by: str        # user_id
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    finalized_at: datetime | None = None
    status: JobStatus
    current_step: DesignJobStep
    result: dict | None = None
    error: str | None = None


class ApprovalRequest(BaseModel):
    """
    Data sent to the frontend when the agent pauses for human review.
    """
    job_id: str
    session_id: str
    floor_plan_summary: dict
    compliance_preview: dict
    constraints_relaxed: list[str] = []
    solver_iterations: int = 0


class ApprovalResponse(BaseModel):
    """Engineer's decision via the browser."""
    job_id: str
    approved: bool
    feedback: str | None = None
