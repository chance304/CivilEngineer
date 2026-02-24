"""Add verification columns to extracted_rules.

Revision ID: 005
Revises: 004
Create Date: 2026-02-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extracted_rules",
        sa.Column(
            "verification_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "extracted_rules",
        sa.Column(
            "verification_notes",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "extracted_rules",
        sa.Column("verification_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extracted_rules", "verification_confidence")
    op.drop_column("extracted_rules", "verification_notes")
    op.drop_column("extracted_rules", "verification_status")
