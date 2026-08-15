"""P2-2：Trace 链路查询 API 集成测试（真实 MySQL）"""

import pytest

_TRACE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS trace_observability (
        trace_id VARCHAR(64) PRIMARY KEY,
        conversation_id VARCHAR(64) NOT NULL,
        exchange_id INT NOT NULL,
        session_id VARCHAR(64),
        root_span_id VARCHAR(64),
        input TEXT, output TEXT, metadata TEXT, tags TEXT,
        created_at DATETIME(3) NOT NULL,
        flushed_at DATETIME(3)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_observability_span (
        span_id VARCHAR(64) PRIMARY KEY,
        trace_id VARCHAR(64) NOT NULL,
        parent_span_id VARCHAR(64),
        kind VARCHAR(32) NOT NULL,
        name VARCHAR(128) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'ok',
        started_at DATETIME(3) NOT NULL,
        ended_at DATETIME(3),
        duration_ms INT,
        input TEXT, output TEXT, metadata TEXT, tags TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_observability_score (
        score_id VARCHAR(64) PRIMARY KEY,
        trace_id VARCHAR(64) NOT NULL,
        span_id VARCHAR(64) NOT NULL,
        metric_name VARCHAR(64) NOT NULL,
        value DECIMAL(5,4) NOT NULL,
        reason TEXT,
        metadata TEXT,
        created_at DATETIME(3) NOT NULL
    )
    """,
]

_SEED_SQL = [
    "INSERT INTO trace_observability (trace_id, conversation_id, exchange_id, root_span_id, created_at) VALUES "
    "('t-100', 'conv-tr-1', 1, 's-root', '2026-08-15 10:00:00.000'), "
    "('t-200', 'conv-tr-1', 2, 's-root-2', '2026-08-15 11:00:00.000'), "
    "('t-300', 'conv-tr-2', 1, 's-root-3', '2026-08-15 12:00:00.000')",
    "INSERT INTO trace_observability_span (span_id, trace_id, parent_span_id, kind, name, status, started_at, ended_at, duration_ms) VALUES "
    "('s-root', 't-100', NULL, 'pipeline', 'chat_execute', 'ok', '2026-08-15 10:00:00.000', '2026-08-15 10:00:01.000', 1000), "
    "('s-r1', 't-100', 's-root', 'retrieval', 'vector_search', 'ok', '2026-08-15 10:00:00.100', '2026-08-15 10:00:00.500', 400), "
    "('s-root-2', 't-200', NULL, 'pipeline', 'chat_execute', 'error', '2026-08-15 11:00:00.000', '2026-08-15 11:00:00.300', 300), "
    "('s-root-3', 't-300', NULL, 'pipeline', 'chat_execute', 'ok', '2026-08-15 12:00:00.000', '2026-08-15 12:00:00.200', 200)",
    "INSERT INTO trace_observability_score (score_id, trace_id, span_id, metric_name, value, reason, created_at) VALUES "
    "('sc-1', 't-100', 's-root', 'faithfulness', 0.9500, 'all claims supported', '2026-08-15 10:00:02.000')",
]


@pytest.mark.asyncio
async def test_trace_list_and_detail(integration_env):
    from sqlalchemy import text

    import app.db.session as _dbs
    from app.db.session import close_db, init_db

    await init_db()
    assert _dbs._session_factory is not None
    async with _dbs._session_factory() as db:
        # 幂等：清掉历史测试残留
        await db.execute(text("DELETE FROM trace_observability_score"))
        await db.execute(text("DELETE FROM trace_observability_span"))
        await db.execute(text("DELETE FROM trace_observability"))
        for ddl in _TRACE_DDL:
            await db.execute(text(ddl))
        for sql in _SEED_SQL:
            await db.execute(text(sql))
        await db.commit()

        from app.api.manage_observability import _query_traces

        # 列表：全部
        records, total = await _query_traces(db, 1, 20, None, None, None, None)
        assert total == 3
        assert any(r["traceId"] == "t-100" for r in records)
        t100 = next(r for r in records if r["traceId"] == "t-100")
        assert t100["spanCount"] == 2
        assert t100["durationMs"] == 1000.0
        assert t100["status"] == "ok"

        # 列表：按会话过滤
        records, total = await _query_traces(db, 1, 20, "conv-tr-1", None, None, None)
        assert total == 2

        # 列表：按状态过滤
        records, total = await _query_traces(db, 1, 20, None, "error", None, None)
        assert total == 1
        assert records[0]["traceId"] == "t-200"

        # 详情：spans + scores
        from app.api.manage_observability import get_trace_detail

        detail = await get_trace_detail("t-100", db, _="")
        data = detail["data"]
        assert data["conversationId"] == "conv-tr-1"
        assert len(data["spans"]) == 2
        root = next(s for s in data["spans"] if s["spanId"] == "s-root")
        assert root["parentSpanId"] is None
        assert root["durationMs"] == 1000
        assert data["scores"][0]["metricName"] == "faithfulness"
        assert data["scores"][0]["value"] == 0.95

    await close_db()
