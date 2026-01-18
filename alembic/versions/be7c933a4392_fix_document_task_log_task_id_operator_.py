"""fix_document_task_log_task_id_operator_id_to_string

Revision ID: be7c933a4392
Revises: 608801d3f53a
Create Date: 2026-05-26 22:17:38.851619

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be7c933a4392"
down_revision: str | None = "608801d3f53a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 将 task_id 和 operator_id 从 BIGINT 改为 VARCHAR(128)，
    # 匹配 migration 690151807873 的意图（其 CREATE TABLE 因表已存在而静默失败）。
    op.alter_column(
        "pipeline_rag_document_task_log",
        "task_id",
        existing_type=sa.BigInteger(),
        type_=sa.String(128),
        existing_nullable=False,
    )
    op.alter_column(
        "pipeline_rag_document_task_log",
        "operator_id",
        existing_type=sa.BigInteger(),
        type_=sa.String(128),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 还原为 BIGINT。字符串数据会尝试转为整数，非数字字符串会失败。
    # 仅在确认列中全是数字字符串时使用。
    op.alter_column(
        "pipeline_rag_document_task_log",
        "operator_id",
        existing_type=sa.String(128),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_rag_document_task_log",
        "task_id",
        existing_type=sa.String(128),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
