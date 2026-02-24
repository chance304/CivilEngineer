"""
SQLModel ORM models — maps to PostgreSQL tables.

All tables include firm_id for multi-tenant row-level security.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(UTC)

import sqlalchemy as sa

# JSON column type
from sqlalchemy import JSON, Text
from sqlmodel import Column, Field, SQLModel


class FirmModel(SQLModel, table=True):
    __tablename__ = "firms"

    firm_id: str = Field(primary_key=True)
    name: str
    country: str = Field(index=True)
    default_jurisdiction: str
    plan: str = "professional"
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class UserModel(SQLModel, table=True):
    __tablename__ = "users"

    user_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    email: str = Field(unique=True, index=True)
    full_name: str
    hashed_password: str
    role: str                              # UserRole enum value
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    last_login: datetime | None = None


class ProjectModel(SQLModel, table=True):
    __tablename__ = "projects"

    project_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    name: str
    client_name: str
    site_address: str = ""
    site_city: str
    site_country: str
    created_by: str = Field(foreign_key="users.user_id")
    status: str = "draft"
    plot_info: dict | None = Field(default=None, sa_column=Column(JSON))
    properties: dict = Field(default_factory=dict, sa_column=Column(JSON))
    requirements: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    __table_args__ = (
        sa.Index("ix_projects_firm_id_status", "firm_id", "status"),
    )


class ProjectAssignmentModel(SQLModel, table=True):
    """Many-to-many: engineers assigned to projects they don't own."""
    __tablename__ = "project_assignments"

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    user_id: str = Field(foreign_key="users.user_id", index=True)
    assigned_at: datetime = Field(default_factory=_utcnow)

    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id"),
    )


class DesignJobModel(SQLModel, table=True):
    __tablename__ = "design_jobs"

    job_id: str = Field(primary_key=True)
    celery_task_id: str = Field(index=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    session_id: str = Field(index=True)
    submitted_by: str = Field(foreign_key="users.user_id")
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    finalized_at: datetime | None = None
    status: str = "pending"
    current_step: str = "loading"
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None

    __table_args__ = (
        sa.Index("ix_design_jobs_firm_id_status", "firm_id", "status"),
    )


class JurisdictionRuleModel(SQLModel, table=True):
    """
    Active building code rules for all jurisdictions.
    Populated from extracted_rules after human review and activation.
    """
    __tablename__ = "jurisdiction_rules"

    rule_id: str = Field(primary_key=True)    # "NP_NBC205_4.2"
    jurisdiction: str = Field(index=True)
    code_version: str
    source_doc_id: str | None = Field(
        default=None, foreign_key="building_code_documents.doc_id"
    )
    source_page: int | None = None
    source_section: str = ""
    category: str = Field(index=True)
    severity: str = Field(index=True)         # "hard" | "soft" | "advisory"
    rule_type: str = ""
    name: str
    description: str
    source: str = ""
    applies_to: list = Field(default_factory=list, sa_column=Column(JSON))
    numeric_value: float | None = None
    unit: str | None = None
    reference_rooms: list = Field(default_factory=list, sa_column=Column(JSON))
    embedding_text: str = ""
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    is_active: bool = True
    effective_from: datetime = Field(default_factory=_utcnow)
    superseded_by: str | None = None       # rule_id of newer version

    __table_args__ = (
        sa.Index("ix_rules_jurisdiction_category", "jurisdiction", "category"),
    )


class BuildingCodeDocumentModel(SQLModel, table=True):
    """Uploaded official building code PDF — source for rule extraction."""
    __tablename__ = "building_code_documents"

    doc_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    jurisdiction: str = Field(index=True)
    code_name: str
    code_version: str
    uploaded_by: str = Field(foreign_key="users.user_id")
    uploaded_at: datetime = Field(default_factory=_utcnow)
    s3_key: str
    status: str = "uploaded"
    # "uploaded" | "extracting" | "review" | "active" | "superseded"
    extraction_job_id: str | None = None
    rules_extracted: int = 0
    rules_approved: int = 0
    extraction_notes: list = Field(default_factory=list, sa_column=Column(JSON))


class ExtractedRuleModel(SQLModel, table=True):
    """Rules extracted by LLM from a building code PDF — awaiting human review."""
    __tablename__ = "extracted_rules"

    extracted_rule_id: str = Field(primary_key=True)
    doc_id: str = Field(
        foreign_key="building_code_documents.doc_id", index=True
    )
    jurisdiction: str = Field(index=True)
    proposed_rule_id: str
    name: str
    description: str
    source_section: str
    source_page: int
    source_text: str = Field(sa_column=Column(Text))
    category: str
    severity: str
    numeric_value: float | None = None
    unit: str | None = None
    confidence: float
    reviewer_approved: bool | None = None
    reviewer_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    # Verification Agent output (second LLM pass)
    verification_status: str = "pending"    # "pending" | "verified" | "flagged" | "unverifiable"
    verification_notes: str = ""            # verifier's feedback; non-empty when flagged
    verification_confidence: float | None = None  # verifier-adjusted confidence score

    __table_args__ = (
        sa.Index("ix_extracted_rules_doc_review", "doc_id", "reviewer_approved"),
    )


# ---------------------------------------------------------------------------
# Decision-tracking tables (Phase 3)
# ---------------------------------------------------------------------------


class ProjectChangeLogModel(SQLModel, table=True):
    """Per-field change history for projects — who changed what and when."""
    __tablename__ = "project_change_log"

    log_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    changed_by: str = Field(foreign_key="users.user_id")
    changed_at: datetime = Field(default_factory=_utcnow)
    field_name: str        # "name", "requirements", "plot_info", "properties", etc.
    old_value: dict | None = Field(default=None, sa_column=Column(JSON))
    new_value: dict | None = Field(default=None, sa_column=Column(JSON))
    change_source: str = "api"   # "api" | "pipeline"

    __table_args__ = (
        sa.Index("ix_project_change_log_project_id", "project_id"),
    )


class RequirementsVersionModel(SQLModel, table=True):
    """Snapshot of DesignRequirements captured at the start of each design job."""
    __tablename__ = "requirements_versions"

    version_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    captured_at: datetime = Field(default_factory=_utcnow)
    requirements: dict = Field(default_factory=dict, sa_column=Column(JSON))
    version_number: int = 1    # monotonically increasing per project


class DesignDecisionLogModel(SQLModel, table=True):
    """Generic one-record-per-node execution log for the design pipeline."""
    __tablename__ = "design_decision_log"

    decision_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    node_name: str            # "validate", "plan", "geometry", "draw"
    occurred_at: datetime = Field(default_factory=_utcnow)
    decision_type: str        # "validation_result", "zone_computed", "geometry_generated", etc.
    iteration: int = 0        # revision cycle number
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))

    __table_args__ = (
        sa.Index("ix_decision_log_project_job", "project_id", "job_id"),
    )


class SolverIterationLogModel(SQLModel, table=True):
    """Detailed per-solve-run record: SAT/UNSAT, placement stats, relaxation info."""
    __tablename__ = "solver_iteration_log"

    iteration_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    iteration_number: int
    started_at: datetime = Field(default_factory=_utcnow)
    solver_status: str           # "SAT" | "UNSAT" | "PARTIAL" | "TIMEOUT"
    placed_room_count: int = 0
    unplaced_room_count: int = 0
    solver_time_s: float = 0.0
    relaxation_type: str | None = None   # None for SAT, else "remove_optional" etc.
    rooms_removed: list = Field(default_factory=list, sa_column=Column(JSON))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON))

    __table_args__ = (
        sa.Index("ix_solver_log_project_job", "project_id", "job_id"),
    )


class ComplianceReportModel(SQLModel, table=True):
    """ComplianceReport persisted to PostgreSQL (also written as JSON file)."""
    __tablename__ = "compliance_reports"

    report_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    generated_at: datetime = Field(default_factory=_utcnow)
    is_compliant: bool = False
    violation_count: int = 0
    warning_count: int = 0
    advisory_count: int = 0
    hard_violations: list = Field(default_factory=list, sa_column=Column(JSON))
    soft_warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    advisories: list = Field(default_factory=list, sa_column=Column(JSON))
    report_path: str | None = None

    __table_args__ = (
        sa.Index("ix_compliance_reports_project_job", "project_id", "job_id"),
    )


class DesignApprovalModel(SQLModel, table=True):
    """Engineer interrupt decision — approve / revise / abort the floor plan."""
    __tablename__ = "design_approvals"

    approval_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    approved_by: str = Field(foreign_key="users.user_id")
    approval_type: str = "floor_plan"   # "floor_plan" | "requirements"
    decision: str                        # "approve" | "revise" | "abort"
    feedback_text: str = ""
    occurred_at: datetime = Field(default_factory=_utcnow)
    revision_count: int = 0


class ClientApprovalModel(SQLModel, table=True):
    """Client (viewer-role) sign-off on a finalized design session."""
    __tablename__ = "client_approvals"

    approval_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    submitted_by: str = Field(foreign_key="users.user_id")
    submitted_at: datetime = Field(default_factory=_utcnow)
    action: str                         # "approved" | "revision_requested"
    notes: str = ""                     # client's revision notes (if any)

    __table_args__ = (
        sa.Index("ix_client_approvals_session", "session_id"),
    )


class ElevationDecisionModel(SQLModel, table=True):
    """Roof type, parapet height, facade material chosen during draw_node."""
    __tablename__ = "elevation_decisions"

    elevation_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id", index=True)
    job_id: str = Field(foreign_key="design_jobs.job_id", index=True)
    session_id: str = Field(index=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    decided_at: datetime = Field(default_factory=_utcnow)
    roof_type: str = ""
    parapet_height_m: float | None = None
    facade_material: str = ""
    num_floors: int = 1
    floor_heights: list = Field(default_factory=list, sa_column=Column(JSON))
    output_paths: list = Field(default_factory=list, sa_column=Column(JSON))
