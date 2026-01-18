"""add_rag_evaluation_table

Revision ID: 4eec58a389b3
Revises: b035743728ba
Create Date: 2026-05-29 09:19:55.029843

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4eec58a389b3"
down_revision: str | None = "b035743728ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_rag_evaluation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("exchange_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("faithfulness_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("answer_relevancy_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("context_precision_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("eval_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("eval_message", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_rag_evaluation_exchange_id"),
        "conversation_rag_evaluation",
        ["exchange_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_rag_evaluation_conversation_id"),
        "conversation_rag_evaluation",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_conversation_rag_evaluation_conversation_id"),
        table_name="conversation_rag_evaluation",
    )
    op.drop_index(
        op.f("ix_conversation_rag_evaluation_exchange_id"), table_name="conversation_rag_evaluation"
    )
    op.drop_table("conversation_rag_evaluation")
