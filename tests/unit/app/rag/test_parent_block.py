import types

import pytest

import app.rag.parent_block as parent_block_module
from app.chat.schema import Evidence
from app.rag.parent_block import ParentBlockElevator


def make_rag_settings(parent_evidence_max_chars=0):
    return types.SimpleNamespace(rag=types.SimpleNamespace(parent_evidence_max_chars=parent_evidence_max_chars))


class FakeSession:
    """按 SQL 文本分派：第一查 parent_block_id，第二查 chunk_text"""

    def __init__(self, child_rows, parent_rows):
        self.child_rows = child_rows
        self.parent_rows = parent_rows
        self.queries = []

    async def execute(self, stmt):
        sql = str(stmt)
        self.queries.append(sql)
        if "parent_block_id" in sql:
            return types.SimpleNamespace(all=lambda: list(self.child_rows))
        if "chunk_text" in sql:
            return types.SimpleNamespace(all=lambda: list(self.parent_rows))
        return types.SimpleNamespace(all=lambda: [])


def ev(chunk_id, score=1.0, source_type="document"):
    return Evidence(
        chunk_id=chunk_id,
        doc_id="doc-1",
        title="t",
        content=f"内容{chunk_id}",
        score=score,
        source_type=source_type,
    )


def child_row(chunk_id, parent_id):
    return types.SimpleNamespace(id=chunk_id, parent_block_id=parent_id)


def parent_row(parent_id, text, path=None):
    return types.SimpleNamespace(id=parent_id, chunk_text=text, section_path=path)


@pytest.fixture
def elevator(monkeypatch):
    monkeypatch.setattr(
        parent_block_module, "settings", make_rag_settings()
    )
    return ParentBlockElevator()


class TestShortCircuits:
    @pytest.mark.asyncio
    async def test_empty_evidences(self, elevator):
        assert await elevator.elevate([]) == []

    @pytest.mark.asyncio
    async def test_no_document_evidences(self, elevator):
        evs = [ev("w1", source_type="web"), ev("w2", source_type="web")]
        assert await elevator.elevate(evs) == evs


class TestElevate:
    @pytest.mark.asyncio
    async def test_replaces_child_with_parent(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "父块内容", "第一章 > 1.1")],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert len(result) == 1
        assert result[0].chunk_id == "c1"
        assert result[0].content == "【章节路径：第一章 > 1.1】\n父块内容"
        assert result[0].score == 1.0

    @pytest.mark.asyncio
    async def test_content_without_path(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "父块内容", None)],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert result[0].content == "父块内容"

    @pytest.mark.asyncio
    async def test_original_score_backfill(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "父块内容")],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert result[0].original_score == 1.0

    @pytest.mark.asyncio
    async def test_original_score_kept_when_set(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "父块内容")],
        )
        e = ev("c1")
        e.original_score = 0.5
        result = await elevator.elevate([e], session)
        assert result[0].original_score == 0.5

    @pytest.mark.asyncio
    async def test_truncation(self, monkeypatch):
        monkeypatch.setattr(
            parent_block_module, "settings", make_rag_settings(parent_evidence_max_chars=10)
        )
        elevator = ParentBlockElevator()
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "很长很长的父块内容", "第一章")],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert result[0].content == "【章节路径：第一章】\n很长..."[:10] + "..."
        assert len(result[0].content) == 13

    @pytest.mark.asyncio
    async def test_no_truncation_within_limit(self, monkeypatch):
        monkeypatch.setattr(
            parent_block_module, "settings", make_rag_settings(parent_evidence_max_chars=100)
        )
        elevator = ParentBlockElevator()
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "短内容", "第一章")],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert result[0].content == "【章节路径：第一章】\n短内容"

    @pytest.mark.asyncio
    async def test_multiple_children_grouped_by_parent(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1"), child_row("c2", "p1"), child_row("c3", "p2")],
            [parent_row("p1", "父块一"), parent_row("p2", "父块二")],
        )
        result = await elevator.elevate([ev("c1", score=0.5), ev("c2", score=0.9), ev("c3", score=0.7)], session)
        assert len(result) == 2
        by_id = {e.chunk_id: e for e in result}
        assert set(by_id) == {"c2", "c3"}
        assert by_id["c2"].content == "父块一"
        assert by_id["c3"].content == "父块二"

    @pytest.mark.asyncio
    async def test_child_without_parent_kept(self, elevator):
        session = FakeSession(
            [child_row("c1", None), child_row("c2", "p1")],
            [parent_row("p1", "父块内容")],
        )
        result = await elevator.elevate([ev("c1"), ev("c2")], session)
        by_id = {e.chunk_id: e for e in result}
        assert by_id["c1"].content == "内容c1"
        assert by_id["c2"].content == "父块内容"

    @pytest.mark.asyncio
    async def test_parent_not_found_child_kept(self, elevator):
        session = FakeSession(
            [child_row("c1", "missing")],
            [],
        )
        result = await elevator.elevate([ev("c1")], session)
        assert result[0].content == "内容c1"

    @pytest.mark.asyncio
    async def test_sorted_by_score_desc(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1"), child_row("c3", "p2")],
            [parent_row("p1", "父块一"), parent_row("p2", "父块二")],
        )
        result = await elevator.elevate(
            [ev("c1", score=0.3), ev("c3", score=0.8)], session
        )
        assert result[0].chunk_id == "c3"
        assert result[1].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_web_evidence_passthrough(self, elevator):
        session = FakeSession(
            [child_row("c1", "p1")],
            [parent_row("p1", "父块内容")],
        )
        evs = [ev("c1"), ev("w1", score=0.4, source_type="web")]
        result = await elevator.elevate(evs, session)
        by_id = {e.chunk_id: e for e in result}
        assert by_id["w1"].content == "内容w1"
