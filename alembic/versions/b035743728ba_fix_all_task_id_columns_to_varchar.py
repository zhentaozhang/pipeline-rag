"""fix_all_task_id_columns_to_varchar

Revision ID: b035743728ba
Revises: be7c933a4392
Create Date: 2026-05-26 23:05:26.792672

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b035743728ba"
down_revision: str | None = "be7c933a4392"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 将所有存储 UUID 字符串的 BIGINT 列改为 VARCHAR(128)
    # 这些列在代码中被写入了 Celery UUID (如 "d4c8f3a2-1b2e...")
    alterations = [
        ("pipeline_rag_document", "last_parse_task_id"),
        ("pipeline_rag_document", "last_index_task_id"),
        ("pipeline_rag_document_structure_node", "parse_task_id"),
        ("pipeline_rag_document_parent_block", "task_id"),
        ("pipeline_rag_document_chunk", "task_id"),
    ]
    for table, column in alterations:
        op.alter_column(
            table,
            column,
            existing_type=sa.BigInteger(),
            type_=sa.String(128),
            existing_nullable=True,
        )


def downgrade() -> None:
    alterations = [
        ("pipeline_rag_document_chunk", "task_id"),
        ("pipeline_rag_document_parent_block", "task_id"),
        ("pipeline_rag_document_structure_node", "parse_task_id"),
        ("pipeline_rag_document", "last_index_task_id"),
        ("pipeline_rag_document", "last_parse_task_id"),
    ]
    for table, column in alterations:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(128),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
