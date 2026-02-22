"""decision tracking tables

Revision ID: 002
Revises: 001
Create Date: 2026-02-22

Adds 7 decision-tracking tables for the design pipeline:
- project_change_log
- requirements_versions
- design_decision_log
- solver_iteration_log
- compliance_reports
- design_approvals
- elevation_decisions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_change_log",
        sa.Column("log_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("changed_by", sa.String, sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("field_name", sa.String, nullable=False),
        sa.Column("old_value", sa.JSON, nullable=True),
        sa.Column("new_value", sa.JSON, nullable=True),
        sa.Column("change_source", sa.String, nullable=False, server_default="api"),
    )
    op.create_index("ix_project_change_log_project_id", "project_change_log", ["project_id"])

    op.create_table(
        "requirements_versions",
        sa.Column("version_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requirements", sa.JSON, nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_requirements_versions_project_id", "requirements_versions", ["project_id"])
    op.create_index("ix_requirements_versions_job_id", "requirements_versions", ["job_id"])

    op.create_table(
        "design_decision_log",
        sa.Column("decision_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("node_name", sa.String, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_type", sa.String, nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False, server_default="0"),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_index("ix_decision_log_project_job", "design_decision_log", ["project_id", "job_id"])

    op.create_table(
        "solver_iteration_log",
        sa.Column("iteration_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("iteration_number", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solver_status", sa.String, nullable=False),
        sa.Column("placed_room_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unplaced_room_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("solver_time_s", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("relaxation_type", sa.String, nullable=True),
        sa.Column("rooms_removed", sa.JSON, nullable=False),
        sa.Column("warnings", sa.JSON, nullable=False),
    )
    op.create_index("ix_solver_log_project_job", "solver_iteration_log", ["project_id", "job_id"])

    op.create_table(
        "compliance_reports",
        sa.Column("report_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_compliant", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("violation_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("advisory_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hard_violations", sa.JSON, nullable=False),
        sa.Column("soft_warnings", sa.JSON, nullable=False),
        sa.Column("advisories", sa.JSON, nullable=False),
        sa.Column("report_path", sa.String, nullable=True),
    )
    op.create_index("ix_compliance_reports_project_job", "compliance_reports", ["project_id", "job_id"])

    op.create_table(
        "design_approvals",
        sa.Column("approval_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("approved_by", sa.String, sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("approval_type", sa.String, nullable=False, server_default="floor_plan"),
        sa.Column("decision", sa.String, nullable=False),
        sa.Column("feedback_text", sa.String, nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_design_approvals_project_id", "design_approvals", ["project_id"])

    op.create_table(
        "elevation_decisions",
        sa.Column("elevation_id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("job_id", sa.String, sa.ForeignKey("design_jobs.job_id"), nullable=False),
        sa.Column("session_id", sa.String, nullable=False, index=True),
        sa.Column("firm_id", sa.String, sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("roof_type", sa.String, nullable=False, server_default=""),
        sa.Column("parapet_height_m", sa.Float, nullable=True),
        sa.Column("facade_material", sa.String, nullable=False, server_default=""),
        sa.Column("num_floors", sa.Integer, nullable=False, server_default="1"),
        sa.Column("floor_heights", sa.JSON, nullable=False),
        sa.Column("output_paths", sa.JSON, nullable=False),
    )
    op.create_index("ix_elevation_decisions_project_id", "elevation_decisions", ["project_id"])


def downgrade() -> None:
    op.drop_table("elevation_decisions")
    op.drop_table("design_approvals")
    op.drop_table("compliance_reports")
    op.drop_table("solver_iteration_log")
    op.drop_table("design_decision_log")
    op.drop_table("requirements_versions")
    op.drop_table("project_change_log")
