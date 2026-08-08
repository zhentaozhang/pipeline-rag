import types

import pytest

import app.rag.channels.keyword as keyword_module
from app.chat.schema import SubQuestion
from app.rag.channels.keyword import KeywordRetrievalChannel


def make_sub_question(**overrides):
    defaults = dict(index=0, text="如何配置数据库", tenant_id="t1")
    defaults.update(overrides)
    return SubQuestion(**defaults)


class TestBuildEsQuery:
    def test_should_clauses(self):
        q = KeywordRetrievalChannel._build_es_query("查询词", make_sub_question(), 10)
        should = q["query"]["bool"]["should"]
        assert len(should) == 4
        assert should[0] == {"match_phrase": {"sectionPath": {"query": "查询词", "boost": 8.0}}}
        assert should[1] == {"match_phrase": {"chunkText": {"query": "查询词", "boost": 5.0}}}
        assert should[2] == {"match_phrase": {"documentName": {"query": "查询词", "boost": 4.0}}}
        assert should[3]["multi_match"]["type"] == "best_fields"
        assert q["query"]["bool"]["minimum_should_match"] == 1
        assert q["size"] == 10

    def test_tenant_filter(self):
        q = KeywordRetrievalChannel._build_es_query("q", make_sub_question(tenant_id="租户A"), 10)
        assert {"term": {"tenantId": "租户A"}} in q["query"]["bool"]["filter"]

    def test_doc_ids_filter_filters_invalid(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(doc_ids=["5", "abc", "0"]), 10
        )
        assert {"terms": {"documentId": [5]}} in q["query"]["bool"]["filter"]

    def test_structure_node_filter(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(structure_node_id=42), 10
        )
        assert {"term": {"structureNodeId": 42}} in q["query"]["bool"]["filter"]

    def test_section_path_wildcard_lowercased(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(section_path="第一章 概述"), 10
        )
        assert {"wildcard": {"sectionPath": {"value": "*第一章 概述*"}}} in q["query"]["bool"]["filter"]

    def test_canonical_path_prefix(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(canonical_path="/document/x"), 10
        )
        assert {"prefix": {"canonicalPath": "/document/x"}} in q["query"]["bool"]["filter"]

    def test_item_index_filter(self):
        q = KeywordRetrievalChannel._build_es_query("q", make_sub_question(item_index=3), 10)
        assert {"term": {"itemIndex": 3}} in q["query"]["bool"]["filter"]

    def test_document_name_hints_bool(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(document_name_hints=["部署", "配置"]), 10
        )
        expected = {
            "bool": {
                "should": [
                    {"wildcard": {"documentName": {"value": "*部署*"}}},
                    {"wildcard": {"documentName": {"value": "*配置*"}}},
                ],
                "minimum_should_match": 1,
            }
        }
        assert expected in q["query"]["bool"]["filter"]

    def test_business_category_and_tag_filters(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q",
            make_sub_question(business_category_hints=["A"], document_tag_hints=["x", "y"]),
            10,
        )
        filters = q["query"]["bool"]["filter"]
        assert {"terms": {"businessCategory": ["A"]}} in filters
        assert {"terms": {"documentTags": ["x", "y"]}} in filters

    def test_no_extra_filters(self):
        q = KeywordRetrievalChannel._build_es_query("q", make_sub_question(), 10)
        filters = q["query"]["bool"]["filter"]
        assert len(filters) == 1


class TestBuildFallbackSql:
    def test_basic_structure(self):
        sql, args = KeywordRetrievalChannel._build_fallback_sql(["配置", "连接"], make_sub_question(), 10)
        assert "pipeline_rag_document_embedding" in sql
        assert "AS similarity" in sql
        assert args[:2] == ["%配置%", "%连接%"]
        assert sql.endswith("LIMIT $4")

    def test_weight_decay(self):
        sql, _ = KeywordRetrievalChannel._build_fallback_sql(["a", "b", "c", "d", "e", "f", "g"], make_sub_question(), 10)
        assert "* 6.0" in sql
        assert "* 5.0" in sql
        assert "* 4.0" in sql
        assert "* 1.0" in sql

    def test_section_like_bonus(self):
        sql, _ = KeywordRetrievalChannel._build_fallback_sql(["配置"], make_sub_question(), 10)
        assert "section_path LIKE $1 THEN 1.5" in sql

    def test_filter_conditions(self):
        sub = make_sub_question(
            tenant_id="t1",
            scope_code="scope1",
            doc_ids=["7"],
            structure_node_id=9,
            section_path="第一章",
            canonical_path="/document",
            item_index=2,
            business_category_hints=["A", "B"],
        )
        sql, args = KeywordRetrievalChannel._build_fallback_sql(["配置"], sub, 10)
        assert "tenant_id = $2" in sql
        assert "scope_code' = $3" in sql
        assert "document_id = ANY($4::bigint[])" in sql
        assert args[1:4] == ["t1", "scope1", [7]]
        assert "structure_node_id = $5" in sql
        assert "section_path LIKE $6" in sql
        assert args[5] == "第一章%"
        assert "canonical_path LIKE $7" in sql
        assert "item_index = $8" in sql
        assert "businessCategory' = ANY(ARRAY[$9, $10])" in sql
        assert args[8:10] == ["A", "B"]

    def test_tail_like_or_clause(self):
        sql, _ = KeywordRetrievalChannel._build_fallback_sql(["甲", "乙"], make_sub_question(), 10)
        assert "(chunk_text LIKE $1 " in sql
        assert "OR chunk_text LIKE $2 OR section_path LIKE $2" in sql

    def test_doc_ids_invalid_filtered(self):
        sql, args = KeywordRetrievalChannel._build_fallback_sql(
            ["配置"], make_sub_question(doc_ids=["3", "x", "0"]), 10
        )
        assert [3] in args


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_blank_text_returns_empty(self):
        channel = KeywordRetrievalChannel()
        assert await channel.retrieve(make_sub_question(text="  ")) == []

    @pytest.mark.asyncio
    async def test_hits_mapping(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                return {
                    "hits": {
                        "hits": [
                            {
                                "_score": 2.5,
                                "_source": {
                                    "chunkId": "c1",
                                    "chunkText": "正文",
                                    "sectionPath": "第一章",
                                    "documentId": "9",
                                },
                            },
                            {
                                "_score": None,
                                "_source": {
                                    "chunkId": "c2",
                                    "chunkText": "正文2",
                                    "documentId": "9",
                                },
                            },
                        ]
                    }
                }

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        channel = KeywordRetrievalChannel()
        results = await channel.retrieve(make_sub_question())
        assert len(results) == 2
        assert results[0].chunk_id == "c1"
        assert results[0].content == "正文"
        assert results[0].title == "第一章"
        assert results[0].score == 2.5
        assert results[0].channel == "keyword"
        assert results[0].doc_id == "9"
        assert results[1].title == "未知文档片段"
        assert results[1].score == 0.0

    @pytest.mark.asyncio
    async def test_top_k_limit_cap(self, monkeypatch):
        captured = {}

        class FakeEs:
            async def search(self, index=None, body=None):
                captured["limit"] = body["size"]
                return {"hits": {"hits": []}}

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=1000)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=1000)))
        channel = KeywordRetrievalChannel()
        await channel.retrieve(make_sub_question())
        assert captured["limit"] == 50

    @pytest.mark.asyncio
    async def test_default_limit_when_non_positive(self, monkeypatch):
        captured = {}

        class FakeEs:
            async def search(self, index=None, body=None):
                captured["limit"] = body["size"]
                return {"hits": {"hits": []}}

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=0)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        channel = KeywordRetrievalChannel()
        await channel.retrieve(make_sub_question())
        assert captured["limit"] == 10

    @pytest.mark.asyncio
    async def test_fallback_pgvector_on_empty_hits(self, monkeypatch):
        calls = {}

        class FakeEs:
            async def search(self, index=None, body=None):
                return {"hits": {"hits": []}}

        async def fake_fetch(sql, *args):
            calls["sql"] = sql
            calls["args"] = args
            return [
                {"chunk_id": 1, "chunk_text": "正文", "section_path": "第一章", "document_id": 5, "document_name": "手册", "similarity": 0.8}
            ]

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        channel = KeywordRetrievalChannel()
        results = await channel.retrieve(make_sub_question(text="配置数据库连接"))
        assert len(results) == 1
        assert results[0].chunk_id == "1"
        assert results[0].title == "第一章"
        assert results[0].score == 0.8
        assert "pipeline_rag_document_embedding" in calls["sql"]

    @pytest.mark.asyncio
    async def test_fallback_pgvector_on_es_error(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                raise RuntimeError("es down")

        async def fake_fetch(sql, *args):
            return []

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        channel = KeywordRetrievalChannel()
        results = await channel.retrieve(make_sub_question(text="配置数据库连接"))
        assert results == []

    @pytest.mark.asyncio
    async def test_fallback_skipped_when_no_terms(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                return {"hits": {"hits": []}}

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", lambda sql, *args: [])
        channel = KeywordRetrievalChannel()
        assert await channel.retrieve(make_sub_question(text="啊")) == []

    @pytest.mark.asyncio
    async def test_fallback_pg_error_returns_empty(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                return {"hits": {"hits": []}}

        async def fake_fetch(sql, *args):
            raise RuntimeError("pg down")

        monkeypatch.setattr(keyword_module, "settings", types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)))
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        channel = KeywordRetrievalChannel()
        assert await channel.retrieve(make_sub_question(text="配置数据库")) == []
