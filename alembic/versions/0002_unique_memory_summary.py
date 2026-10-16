"""add unique constraint to memory summary dialogue_code

Revision ID: 0002_unique_memory_summary
Revises: 0001_baseline
Create Date: 2026-10-16 15:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_unique_memory_summary"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 清理历史可能存在的重复行，保留每个 dialogue_code 中 id 最大的记录
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM pipeline_rag_chat_memory_summary
            WHERE id NOT IN (
                SELECT max_id FROM (
                    SELECT MAX(id) AS max_id
                    FROM pipeline_rag_chat_memory_summary
                    GROUP BY dialogue_code
                ) AS tmp
            )
            """
        )
    )

    # 2. 删除原普通索引并创建唯一索引
    op.drop_index(
        op.f("ix_pipeline_rag_chat_memory_summary_dialogue_code"),
        table_name="pipeline_rag_chat_memory_summary",
    )
    op.create_index(
        op.f("ix_pipeline_rag_chat_memory_summary_dialogue_code"),
        "pipeline_rag_chat_memory_summary",
        ["dialogue_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pipeline_rag_chat_memory_summary_dialogue_code"),
        table_name="pipeline_rag_chat_memory_summary",
    )
    op.create_index(
        op.f("ix_pipeline_rag_chat_memory_summary_dialogue_code"),
        "pipeline_rag_chat_memory_summary",
        ["dialogue_code"],
        unique=False,
    )
