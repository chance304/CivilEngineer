"""Add client_approvals table.

Revision ID: 004
Revises: 003
Create Date: 2026-02-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_approvals",
        sa.Column("approval_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("firm_id", sa.Text(), sa.ForeignKey("firms.firm_id"), nullable=False),
        sa.Column("submitted_by", sa.Text(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_client_approvals_session", "client_approvals", ["session_id"])
    op.create_index("ix_client_approvals_project", "client_approvals", ["project_id"])
    op.create_index("ix_client_approvals_firm", "client_approvals", ["firm_id"])


def downgrade() -> None:
    op.drop_index("ix_client_approvals_firm",    "client_approvals")
    op.drop_index("ix_client_approvals_project", "client_approvals")
    op.drop_index("ix_client_approvals_session", "client_approvals")
    op.drop_table("client_approvals")
