"""add_pipeline_stage_to_document

Revision ID: 052a337bd8b2
Revises: 06faca118073
Create Date: 2026-06-02 16:12:15.598908

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "052a337bd8b2"
down_revision: str | None = "06faca118073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pipeline_rag_document", sa.Column("pipeline_stage", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_rag_document", "pipeline_stage")
