"""
SQLModel ORM models — maps to PostgreSQL tables.

All tables include firm_id for multi-tenant row-level security.
"""

from __future__ import annotations

from datetime import UTC, datetime


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

    __table_args__ = (
        sa.Index("ix_extracted_rules_doc_review", "doc_id", "reviewer_approved"),
    )
