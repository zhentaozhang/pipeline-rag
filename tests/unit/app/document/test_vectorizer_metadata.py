"""VectorizerService 落盘元数据透传测试。

回归背景：`_write_to_pgvector` 曾在 `metadata_json` 中引用三个未定义名
（`scope_code` / `business_category` / `document_tags`）。这三个名字本是
`vectorize()` 的形参，但 `vectorize()` 调用 `_write_to_pgvector()` 时没有透传，
于是当 chunk 自身未挂载同名属性（`getattr` 返回假值 → `or` 右侧被求值）时会抛
`NameError`，被 Celery 任务层的 `except Exception` 吞成"向量化失败"。

本文件用于锁死该行为：文档级元数据必须能透传到 metadata_json，且缺失时不得报错。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest

from app.document.chunker import Chunk
from app.document.vectorizer import VectorizerService

_METADATA_JSON_INDEX = 17


class _FakeConn:
    """记录 execute / executemany 调用的假连接。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    async def execute(self, sql: str, *args: object) -> None:
        self.executed.append((sql, args))

    async def executemany(self, sql: str, values: list[tuple]) -> None:
        self.executemany_calls.append((sql, list(values)))


class _FakeProvider:
    """最小 EmbeddingProvider 替身，避免真实网络调用。"""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def dimensions(self) -> int:
        return 3


@pytest.fixture
def fake_pg(monkeypatch: pytest.MonkeyPatch) -> _FakeConn:
    conn = _FakeConn()

    @asynccontextmanager
    async def _fake_transaction():
        yield conn

    import app.infra.pg as pg_module

    monkeypatch.setattr(pg_module, "transaction", _fake_transaction)
    return conn


def _chunk(chunk_id: str, chunk_type: str = "child") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="d1",
        content="章节内容",
        chunk_index=0,
        chunk_type=chunk_type,
        token_count=4,
    )


def _metadata_of(conn: _FakeConn) -> dict:
    assert conn.executemany_calls, "应至少写入一次 embedding"
    _sql, values = conn.executemany_calls[-1]
    assert values, "embed_values 不应为空"
    return json.loads(values[0][_METADATA_JSON_INDEX])


async def test_write_to_pgvector_tolerates_missing_chunk_metadata(fake_pg: _FakeConn) -> None:
    """chunk 未挂载 scope/tags 属性且文档级参数为空时，不得抛 NameError。"""
    service = VectorizerService(provider=_FakeProvider())
    chunks = [_chunk("c1")]

    await service._write_to_pgvector(chunks, chunks, [[0.1, 0.2, 0.3]])

    metadata = _metadata_of(fake_pg)
    assert metadata["scope_code"] == ""
    assert metadata["businessCategory"] == ""
    assert metadata["documentTags"] == ""


async def test_vectorize_forwards_document_metadata(fake_pg: _FakeConn) -> None:
    """vectorize() 必须把文档级元数据透传到 _write_to_pgvector。"""
    service = VectorizerService(provider=_FakeProvider())
    chunks = [_chunk("c1"), _chunk("p1", chunk_type="parent")]

    written = await service.vectorize(
        chunks,
        task_id="t1",
        document_name="部署手册",
        scope_code="deployment",
        business_category="安装部署",
        document_tags="deployment,manual",
    )

    assert written == 1, "仅 child chunk 生成 embedding"
    metadata = _metadata_of(fake_pg)
    assert metadata["scope_code"] == "deployment"
    assert metadata["businessCategory"] == "安装部署"
    assert metadata["documentTags"] == "deployment,manual"


async def test_chunk_level_metadata_wins_over_document_level(fake_pg: _FakeConn) -> None:
    """chunk 自身已挂载元数据时，优先使用 chunk 级（getattr 命中即短路）。"""
    service = VectorizerService(provider=_FakeProvider())
    chunk = _chunk("c1")
    chunk.scope_code = "troubleshooting"  # type: ignore[attr-defined]
    chunk.business_category = "故障排查"  # type: ignore[attr-defined]
    chunk.document_tags = "troubleshooting"  # type: ignore[attr-defined]

    await service.vectorize(
        [chunk],
        task_id="t1",
        scope_code="deployment",
        business_category="安装部署",
        document_tags="deployment",
    )

    metadata = _metadata_of(fake_pg)
    assert metadata["scope_code"] == "troubleshooting"
    assert metadata["businessCategory"] == "故障排查"
    assert metadata["documentTags"] == "troubleshooting"
