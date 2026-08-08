import types

import pytest

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk, ChunkStrategyType
from app.document.chunker.pipeline import ChunkPipeline
from app.document.chunker.recursive import RecursiveChunker
from app.document.chunker.semantic import SemanticChunker
from app.document.chunker.sentence_splitter import split_text
from app.document.chunker.structure import StructureChunker
from app.document.chunker.utils import count_tokens


def make_chunk(content, chunk_index=0, token_count=0, **kw):
    return Chunk(
        chunk_id=f"c{chunk_index}",
        doc_id="d1",
        content=content,
        chunk_index=chunk_index,
        token_count=token_count or len(content),
        **kw,
    )


class TestSplitText:
    def test_splits_on_sentence_boundaries(self):
        out = split_text("第一句。第二句！第三句\n第四句。", chunk_size=10)
        assert out == ["第一句。第二句！", "第三句第四句。"]

    def test_respects_chunk_size(self):
        text = "。".join(f"句子{i}" for i in range(100))
        out = split_text(text, chunk_size=30)
        assert len(out) > 1
        assert all(len(c) <= 30 for c in out)

    def test_blank(self):
        assert split_text("   \n ") == []
        assert split_text("") == []


class TestCountTokens:
    def test_fallback_to_len(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "tiktoken", None)
        assert count_tokens("你好") == 2


class TestRecursiveChunker:
    @pytest.mark.asyncio
    async def test_filters_short_chunks(self):
        text = "短。" + "很长" * 40 + "。"
        chunks = await RecursiveChunker().chunk(text, "d1", ChunkConfig(min_chunk_size=50))
        assert all(len(c.content) >= 50 for c in chunks)
        assert all(c.doc_id == "d1" for c in chunks)

    @pytest.mark.asyncio
    async def test_splitter_error_returns_empty(self, monkeypatch):
        def boom(text, chunk_size):
            raise RuntimeError("split fail")

        monkeypatch.setattr(
            "app.document.chunker.recursive.split_text", boom
        )
        chunks = await RecursiveChunker().chunk("x" * 200, "d1", ChunkConfig())
        assert chunks == []

    @pytest.mark.asyncio
    async def test_chunk_parents_small_passthrough(self):
        parent = make_chunk("小内容", chunk_index=0, token_count=10)
        children = await RecursiveChunker().chunk_parents([parent], ChunkConfig(chunk_size=512))
        assert len(children) == 1
        assert children[0].parent_chunk_id == parent.chunk_id
        assert children[0].chunk_type == "child"
        assert children[0].content == "小内容"

    @pytest.mark.asyncio
    async def test_chunk_parents_large_split(self):
        parent = make_chunk("很长句子。" * 120, chunk_index=3, token_count=500, section_title="标题")
        children = await RecursiveChunker().chunk_parents([parent], ChunkConfig(chunk_size=200, min_chunk_size=10))
        assert len(children) > 1
        assert all(c.section_title == "标题" for c in children)


class TestSemanticChunker:
    @pytest.mark.asyncio
    async def test_no_chunks_passthrough(self):
        assert await SemanticChunker().chunk([], ChunkConfig()) == []

    @pytest.mark.asyncio
    async def test_single_passthrough(self):
        c = make_chunk("唯一")
        assert await SemanticChunker().chunk([c], ChunkConfig()) == [c]

    @pytest.mark.asyncio
    async def test_merges_similar(self, monkeypatch):
        monkeypatch.setattr(
            "app.config.get_settings",
            lambda: types.SimpleNamespace(chunk=types.SimpleNamespace(semantic_similarity_threshold=0.0)),
        )
        chunks = [
            make_chunk("配置数据库连接字符串", chunk_index=0),
            make_chunk("数据库连接配置", chunk_index=1),
        ]
        out = await SemanticChunker().chunk(chunks, ChunkConfig(max_chunk_size=10000))
        assert len(out) == 1
        assert "配置数据库连接字符串" in out[0].content

    @pytest.mark.asyncio
    async def test_splits_dissimilar(self, monkeypatch):
        monkeypatch.setattr(
            "app.config.get_settings",
            lambda: types.SimpleNamespace(chunk=types.SimpleNamespace(semantic_similarity_threshold=0.9)),
        )
        chunks = [
            make_chunk("第一块内容", chunk_index=0),
            make_chunk("完全不同的另一块", chunk_index=1),
        ]
        out = await SemanticChunker().chunk(chunks, ChunkConfig())
        assert len(out) == 2
        assert [c.chunk_index for c in out] == [0, 1]

    @pytest.mark.asyncio
    async def test_merge_respects_max_size(self, monkeypatch):
        monkeypatch.setattr(
            "app.config.get_settings",
            lambda: types.SimpleNamespace(chunk=types.SimpleNamespace(semantic_similarity_threshold=0.0)),
        )
        chunks = [
            make_chunk("相同词汇的文本", chunk_index=0, token_count=100),
            make_chunk("相同词汇的另一", chunk_index=1, token_count=100),
        ]
        out = await SemanticChunker().chunk(chunks, ChunkConfig(max_chunk_size=150))
        assert len(out) == 2


class FakeNode:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeSession:
    def __init__(self, doc_internal_id=1, nodes=None):
        self.doc_internal_id = doc_internal_id
        self.nodes = nodes or []
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return FakeScalar(self.doc_internal_id)
        return FakeScalars(self.nodes)


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeScalars:
    def __init__(self, nodes):
        self.nodes = nodes

    def scalars(self):
        return self

    def all(self):
        return self.nodes


class TestStructureChunker:
    @pytest.mark.asyncio
    async def test_document_not_found(self, monkeypatch):
        monkeypatch.setattr(
            "app.db.session._session_factory",
            lambda: FakeSession(doc_internal_id=None),
        )
        out = await StructureChunker().chunk("t", "d1", ChunkConfig())
        assert out == []

    @pytest.mark.asyncio
    async def test_builds_parent_chunks(self, monkeypatch):
        node = FakeNode(
            node_no=1, node_type=2, depth=1, node_code="1.1", title="安装",
            anchor_text="anchor", canonical_path="/1/1", section_path="安装",
            content_text="内容" * 30, item_index=1, id=42,
        )
        monkeypatch.setattr(
            "app.db.session._session_factory",
            lambda: FakeSession(doc_internal_id=1, nodes=[node]),
        )
        out = await StructureChunker().chunk("t", "d1", ChunkConfig(min_chunk_size=10))
        assert len(out) == 1
        c = out[0]
        assert c.chunk_type == "parent"
        assert c.section_title == "安装"
        assert c.structure_node_id == 42
        assert c.structure_node_type == 2
        assert c.item_index == 1

    @pytest.mark.asyncio
    async def test_short_content_skipped(self, monkeypatch):
        node = FakeNode(
            node_no=1, node_type=1, depth=0, node_code="", title="",
            anchor_text="", canonical_path="", section_path="",
            content_text="短", item_index=0, id=1,
        )
        monkeypatch.setattr(
            "app.db.session._session_factory",
            lambda: FakeSession(doc_internal_id=1, nodes=[node]),
        )
        out = await StructureChunker().chunk("t", "d1", ChunkConfig())
        assert out == []


class TestChunkPipeline:
    @pytest.mark.asyncio
    async def test_recursive_only(self, monkeypatch):
        class FakeRecursive:
            async def chunk(self, text, doc_id, config):
                return [make_chunk("内容内容内容", chunk_index=0, token_count=20)]

        monkeypatch.setattr(
            "app.document.chunker.pipeline.RecursiveChunker",
            lambda: FakeRecursive(),
        )
        out = await ChunkPipeline([ChunkStrategyType.RECURSIVE]).run("t", "d1")
        assert len(out) == 1
        assert out[0].chunk_type == "child"

    @pytest.mark.asyncio
    async def test_structure_without_recursive_flattens(self, monkeypatch):
        class FakeStructure:
            async def chunk(self, text, doc_id, config):
                return [make_chunk("父内容", chunk_index=0, token_count=20, chunk_type="parent")]

        monkeypatch.setattr(
            "app.document.chunker.pipeline.StructureChunker",
            lambda: FakeStructure(),
        )
        out = await ChunkPipeline([ChunkStrategyType.STRUCTURE]).run("t", "d1")
        assert len(out) == 1
        assert out[0].chunk_type == "child"

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self, monkeypatch):
        class FakeRecursive:
            async def chunk(self, text, doc_id, config):
                return []

        class FakeLLM:
            async def chunk(self, text, doc_id, config):
                return []

        monkeypatch.setattr(
            "app.document.chunker.pipeline.RecursiveChunker",
            lambda: FakeRecursive(),
        )
        monkeypatch.setattr(
            "app.document.chunker.pipeline.LLMChunker",
            lambda: FakeLLM(),
        )
        out = await ChunkPipeline([ChunkStrategyType.LLM]).run("t", "d1")
        assert out == []
