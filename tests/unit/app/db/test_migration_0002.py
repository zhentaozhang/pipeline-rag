"""0002_unique_memory_summary 迁移去重 SQL 与唯一约束测试。

验证：
1. 迁移脚本中的去重 SQL 能够安全清理历史重复 dialogue_code 记录，保留每个分组中 MAX(id) 的最新记录。
2. 清理后能够在 dialogue_code 上创建唯一约束/索引。
3. 唯一约束生效，防止后续重复写入。
"""

import pytest
import sqlalchemy as sa
from sqlalchemy import text


def test_migration_0002_deduplication_sql_and_unique_constraint():
    # 使用内存 SQLite 验证去重 SQL 兼容性与逻辑正确性
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        # 1. 模拟迁移前表结构（带普通索引，允许重复 dialogue_code）
        conn.execute(
            text(
                """
                CREATE TABLE pipeline_rag_chat_memory_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialogue_code VARCHAR(128) NOT NULL,
                    summary_text TEXT,
                    summary_version INTEGER DEFAULT 1
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX ix_pipeline_rag_chat_memory_summary_dialogue_code
                ON pipeline_rag_chat_memory_summary (dialogue_code)
                """
            )
        )

        # 2. 插入重复数据模拟历史脏数据
        conn.execute(
            text(
                """
                INSERT INTO pipeline_rag_chat_memory_summary (id, dialogue_code, summary_text)
                VALUES
                    (1, 'session_A', 'old_summary_1'),
                    (2, 'session_A', 'old_summary_2'),
                    (3, 'session_B', 'summary_B_1'),
                    (4, 'session_A', 'latest_summary_A'),
                    (5, 'session_C', 'summary_C_1'),
                    (6, 'session_B', 'latest_summary_B')
                """
            )
        )

        # 3. 执行迁移 0002 中的去重 SQL
        dedup_sql = """
            DELETE FROM pipeline_rag_chat_memory_summary
            WHERE id NOT IN (
                SELECT max_id FROM (
                    SELECT MAX(id) AS max_id
                    FROM pipeline_rag_chat_memory_summary
                    GROUP BY dialogue_code
                ) AS tmp
            )
        """
        conn.execute(text(dedup_sql))

        # 4. 验证去重结果：每个 dialogue_code 仅保留 MAX(id)
        rows = conn.execute(
            text(
                "SELECT id, dialogue_code, summary_text FROM pipeline_rag_chat_memory_summary ORDER BY id"
            )
        ).fetchall()

        assert len(rows) == 3
        assert rows[0] == (4, "session_A", "latest_summary_A")
        assert rows[1] == (5, "session_C", "summary_C_1")
        assert rows[2] == (6, "session_B", "latest_summary_B")

        # 5. 模拟迁移中的 drop 原索引并创建唯一索引
        conn.execute(text("DROP INDEX ix_pipeline_rag_chat_memory_summary_dialogue_code"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX ix_pipeline_rag_chat_memory_summary_dialogue_code
                ON pipeline_rag_chat_memory_summary (dialogue_code)
                """
            )
        )

        # 6. 验证唯一索引生效：插入同名 dialogue_code 应报错
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO pipeline_rag_chat_memory_summary (dialogue_code, summary_text)
                    VALUES ('session_A', 'duplicate_row')
                    """
                )
            )
