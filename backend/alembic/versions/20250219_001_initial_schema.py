"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-02-19

Creates all Phase 2 tables:
- firms
- users
- projects
- project_assignments
- design_jobs
- jurisdiction_rules
- building_code_documents
- extracted_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # firms
    # ------------------------------------------------------------------
    op.create_table(
        "firms",
        sa.Column("firm_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("default_jurisdiction", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="professional"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_firms_country", "firms", ["country"])

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("firm_id", sa.String(), sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_login", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_firm_id", "users", ["firm_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("firm_id", sa.String(), sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("site_address", sa.String(), nullable=False, server_default=""),
        sa.Column("site_city", sa.String(), nullable=False),
        sa.Column("site_country", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("plot_info", sa.JSON(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("requirements", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_projects_firm_id_status", "projects", ["firm_id", "status"])

    # ------------------------------------------------------------------
    # project_assignments
    # ------------------------------------------------------------------
    op.create_table(
        "project_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"),
                  nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "user_id"),
    )
    op.create_index("ix_project_assignments_project_id", "project_assignments", ["project_id"])
    op.create_index("ix_project_assignments_user_id", "project_assignments", ["user_id"])

    # ------------------------------------------------------------------
    # building_code_documents (must come before jurisdiction_rules for FK)
    # ------------------------------------------------------------------
    op.create_table(
        "building_code_documents",
        sa.Column("doc_id", sa.String(), primary_key=True),
        sa.Column("firm_id", sa.String(), sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("code_name", sa.String(), nullable=False),
        sa.Column("code_version", sa.String(), nullable=False),
        sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("s3_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="uploaded"),
        sa.Column("extraction_job_id", sa.String(), nullable=True),
        sa.Column("rules_extracted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rules_approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extraction_notes", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_building_code_documents_firm_id", "building_code_documents", ["firm_id"])
    op.create_index("ix_building_code_documents_jurisdiction", "building_code_documents",
                    ["jurisdiction"])

    # ------------------------------------------------------------------
    # jurisdiction_rules
    # ------------------------------------------------------------------
    op.create_table(
        "jurisdiction_rules",
        sa.Column("rule_id", sa.String(), primary_key=True),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("code_version", sa.String(), nullable=False),
        sa.Column("source_doc_id", sa.String(),
                  sa.ForeignKey("building_code_documents.doc_id"), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(), nullable=False, server_default=""),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("rule_type", sa.String(), nullable=False, server_default=""),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default=""),
        sa.Column("applies_to", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("reference_rooms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("embedding_text", sa.String(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("effective_from", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("superseded_by", sa.String(), nullable=True),
    )
    op.create_index("ix_rules_jurisdiction_category", "jurisdiction_rules",
                    ["jurisdiction", "category"])

    # ------------------------------------------------------------------
    # extracted_rules
    # ------------------------------------------------------------------
    op.create_table(
        "extracted_rules",
        sa.Column("extracted_rule_id", sa.String(), primary_key=True),
        sa.Column("doc_id", sa.String(),
                  sa.ForeignKey("building_code_documents.doc_id"), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("proposed_rule_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("source_section", sa.String(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reviewer_approved", sa.Boolean(), nullable=True),
        sa.Column("reviewer_notes", sa.String(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_extracted_rules_doc_review", "extracted_rules",
                    ["doc_id", "reviewer_approved"])

    # ------------------------------------------------------------------
    # design_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "design_jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("celery_task_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"),
                  nullable=False),
        sa.Column("firm_id", sa.String(), sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("submitted_by", sa.String(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("current_step", sa.String(), nullable=False, server_default="loading"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )
    op.create_index("ix_design_jobs_project_id", "design_jobs", ["project_id"])
    op.create_index("ix_design_jobs_firm_id_status", "design_jobs", ["firm_id", "status"])
    op.create_index("ix_design_jobs_celery_task_id", "design_jobs", ["celery_task_id"])
    op.create_index("ix_design_jobs_session_id", "design_jobs", ["session_id"])


def downgrade() -> None:
    op.drop_table("design_jobs")
    op.drop_table("extracted_rules")
    op.drop_table("jurisdiction_rules")
    op.drop_table("building_code_documents")
    op.drop_table("project_assignments")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("firms")
