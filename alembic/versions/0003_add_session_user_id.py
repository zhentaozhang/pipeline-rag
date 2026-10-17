"""add user_id column and index to conversation_session

Revision ID: 0003_add_session_user_id
Revises: 0002_unique_memory_summary
Create Date: 2026-10-17 09:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_add_session_user_id"
down_revision: str | None = "0002_unique_memory_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_session",
        sa.Column("user_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_conversation_session_user_id"),
        "conversation_session",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_session_user_id"), table_name="conversation_session")
    op.drop_column("conversation_session", "user_id")
