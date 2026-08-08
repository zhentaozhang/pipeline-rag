import types

import pytest

import app.rag.channels.vector as vector_module
from app.chat.schema import SubQuestion
from app.rag.channels.vector import VectorRetrievalChannel


def make_sub_question(**overrides):
    defaults = dict(index=0, text="如何配置数据库", tenant_id="")
    defaults.update(overrides)
    return SubQuestion(**defaults)


class FakeEmbeddingClient:
    def __init__(self, embedding=None, error=None):
        self.embedding = embedding if embedding is not None else [0.1, 0.2, 0.3]
        self.error = error
        self.calls = []
        self.embeddings = types.SimpleNamespace(create=self._create)

    async def _create(self, model=None, input=None):
        self.calls.append((model, input))
        if self.error:
            raise self.error
        return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=self.embedding)])


@pytest.fixture
def make_channel(monkeypatch):
    def _make(embedding=None, error=None, vector_top_k=20):
        client = FakeEmbeddingClient(embedding=embedding, error=error)
        monkeypatch.setattr(
            vector_module,
            "get_embedding_client",
            lambda: client,
        )
        monkeypatch.setattr(
            vector_module,
            "settings",
            types.SimpleNamespace(
                llm=types.SimpleNamespace(embedding_model="emb-model"),
                rag=types.SimpleNamespace(vector_top_k=vector_top_k),
            ),
        )
        channel = VectorRetrievalChannel()
        return channel, client

    return _make


class TestBuildSql:
    def test_embedding_first_param(self):
        sql, args = VectorRetrievalChannel._build_sql(make_sub_question(), "[1,2]", 10)
        assert args[0] == "[1,2]"
        assert "1 - (embedding <=> $1::vector) AS similarity" in sql
        assert "ORDER BY similarity DESC LIMIT $2" in sql

    def test_tenant_and_scope(self):
        sub = make_sub_question(tenant_id="t1", scope_code="s1")
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "tenant_id = $2" in sql
        assert "scope_code' = $3" in sql
        assert args[1:3] == ["t1", "s1"]

    def test_doc_ids_any(self):
        sub = make_sub_question(tenant_id="t1", doc_ids=["5", "x", "0"])
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "tenant_id = $2" in sql
        assert "document_id = ANY($3::bigint[])" in sql
        assert args[2] == [5]

    def test_structure_section_canonical_item(self):
        sub = make_sub_question(
            tenant_id="t1",
            structure_node_id=9,
            section_path="第一章",
            canonical_path="/document",
            item_index=2,
        )
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "structure_node_id = $3" in sql
        assert args[2] == 9
        assert "section_path LIKE $4" in sql
        assert args[3] == "第一章%"
        assert "canonical_path LIKE $5" in sql
        assert "item_index = $6" in sql

    def test_document_name_ilike_any(self):
        sub = make_sub_question(tenant_id="t1", document_name_hints=["部署", "配置"])
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "documentName' ILIKE ANY(ARRAY[$3, $4])" in sql
        assert args[2:4] == ["%部署%", "%配置%"]

    def test_business_category_any(self):
        sub = make_sub_question(tenant_id="t1", business_category_hints=["A", "B"])
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "businessCategory' = ANY(ARRAY[$3, $4])" in sql
        assert args[2:4] == ["A", "B"]

    def test_document_tag_overlap(self):
        sub = make_sub_question(tenant_id="t1", document_tag_hints=["x", "y"])
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 10)
        assert "&& ARRAY[$3, $4]" in sql
        assert args[2:4] == ["x", "y"]

    def test_limit_param(self):
        sub = make_sub_question(tenant_id="t1", document_name_hints=["手册"])
        sql, args = VectorRetrievalChannel._build_sql(sub, "[1]", 25)
        assert "tenant_id = $2" in sql
        assert "ILIKE ANY(ARRAY[$3])" in sql
        assert "LIMIT $4" in sql
        assert args[-1] == 25


class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_calls_api(self, make_channel):
        channel, client = make_channel()
        embedding = await channel._embed("查询文本")
        assert embedding == [0.1, 0.2, 0.3]
        assert client.calls[0][0] == "emb-model"
        assert client.calls[0][1] == "查询文本"

    @pytest.mark.asyncio
    async def test_embed_error(self, make_channel):
        channel, _ = make_channel(error=RuntimeError("no key"))
        with pytest.raises(RuntimeError):
            await channel._embed("q")


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_success_mapping(self, make_channel, monkeypatch):
        channel, client = make_channel()

        captured = {}

        async def fake_fetch(sql, *args):
            captured["sql"] = sql
            captured["args"] = args
            return [
                {"chunk_id": 1, "content": "正文", "section_path": "第一章", "document_id": 5, "document_name": "手册", "similarity": 0.9}
            ]

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        results = await channel.retrieve(make_sub_question())
        assert len(results) == 1
        assert results[0].chunk_id == "1"
        assert results[0].content == "正文"
        assert results[0].title == "第一章"
        assert results[0].score == 0.9
        assert results[0].channel == "vector"
        assert results[0].doc_id == "5"
        assert captured["args"][0] == "[0.1,0.2,0.3]"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_document_name(self, make_channel, monkeypatch):
        channel, _ = make_channel()

        async def fake_fetch(sql, *args):
            return [
                {"chunk_id": 1, "content": "正文", "section_path": "", "document_id": 5, "document_name": "部署手册", "similarity": 0.5}
            ]

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        results = await channel.retrieve(make_sub_question())
        assert results[0].title == "部署手册"

    @pytest.mark.asyncio
    async def test_title_unknown_fallback(self, make_channel, monkeypatch):
        channel, _ = make_channel()

        async def fake_fetch(sql, *args):
            return [
                {"chunk_id": 1, "content": "正文", "section_path": "", "document_id": 5, "document_name": "", "similarity": 0.5}
            ]

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        results = await channel.retrieve(make_sub_question())
        assert results[0].title == "未知文档片段"

    @pytest.mark.asyncio
    async def test_embed_failure_returns_empty(self, make_channel):
        channel, _ = make_channel(error=RuntimeError("embed down"))
        assert await channel.retrieve(make_sub_question()) == []

    @pytest.mark.asyncio
    async def test_pg_failure_returns_empty(self, make_channel, monkeypatch):
        channel, _ = make_channel()

        async def fake_fetch(sql, *args):
            raise RuntimeError("pg down")

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        assert await channel.retrieve(make_sub_question()) == []

    @pytest.mark.asyncio
    async def test_top_k_cap_fifty(self, make_channel, monkeypatch):
        channel, _ = make_channel(vector_top_k=1000)

        captured = {}

        async def fake_fetch(sql, *args):
            captured["limit"] = args[-1]
            return []

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        await channel.retrieve(make_sub_question())
        assert captured["limit"] == 50

    @pytest.mark.asyncio
    async def test_default_limit_when_non_positive(self, make_channel, monkeypatch):
        channel, _ = make_channel(vector_top_k=0)

        captured = {}

        async def fake_fetch(sql, *args):
            captured["limit"] = args[-1]
            return []

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        await channel.retrieve(make_sub_question())
        assert captured["limit"] == 10
