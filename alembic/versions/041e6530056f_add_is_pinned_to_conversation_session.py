"""add_is_pinned_to_conversation_session

Revision ID: 041e6530056f
Revises: 4eec58a389b3
Create Date: 2026-05-30 22:59:20.358130

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "041e6530056f"
down_revision: str | None = "4eec58a389b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_session",
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "conversation_session",
        sa.Column("pinned_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_session", "pinned_at")
    op.drop_column("conversation_session", "is_pinned")
