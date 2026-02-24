"""add finalized_at to design_jobs

Revision ID: 003
Revises: 002
Create Date: 2026-02-24

Adds:
- design_jobs.finalized_at (nullable DateTime) — set when a session passes the
  documentation completeness gate via POST /projects/{id}/design/{session_id}/finalize
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "design_jobs",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("design_jobs", "finalized_at")
