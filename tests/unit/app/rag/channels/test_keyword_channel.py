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
        """Task 4 起：只有一条 multi_match（OR）+ 命中的结构化子句，不再有整句 match_phrase。"""
        q = KeywordRetrievalChannel._build_es_query("查询词", make_sub_question(), 10)
        should = q["query"]["bool"]["should"]
        assert len(should) == 1
        assert should[0]["multi_match"]["type"] == "best_fields"
        assert should[0]["multi_match"]["operator"] == "or"
        assert should[0]["multi_match"]["fields"] == [
            "sectionPath^3",
            "documentName^2",
            "knowledgeScopeName^1",
            "chunkText",
        ]
        assert q["query"]["bool"]["minimum_should_match"] == 1
        assert q["size"] == 10

    def test_no_whole_sentence_match_phrase(self):
        q = KeywordRetrievalChannel._build_es_query("查询词", make_sub_question(), 10)
        for clause in q["query"]["bool"]["should"]:
            if "match_phrase" in clause:
                payload = clause["match_phrase"]
                body = payload[next(iter(payload))]
                query = body["query"] if isinstance(body, dict) else body
                assert query != "查询词"

    def test_clause_token_adds_structured_clause(self):
        q = KeywordRetrievalChannel._build_es_query(
            "第9条规定了什么", make_sub_question(text="第9条规定了什么"), 10
        )
        should = q["query"]["bool"]["should"]
        assert {"match_phrase": {"sectionPath": {"query": "第9条", "boost": 8.0}}} in should
        assert {"match_phrase": {"chunkText": {"query": "第9条", "boost": 4.0}}} in should
        assert q["query"]["bool"]["should"][0]["multi_match"]["query"] == "第9条规定了什么"

    def test_structured_tokens_cover_doc_grade_city_subclause(self):
        q = KeywordRetrievalChannel._build_es_query(
            "《差旅管理制度》9.1 总监级 M4+ A类城市", make_sub_question(), 10
        )
        should = q["query"]["bool"]["should"]
        assert {"match_phrase": {"chunkText": {"query": "9.1", "boost": 6.0}}} in should
        assert {"match_phrase": {"documentName": {"query": "差旅管理制度", "boost": 5.0}}} in should
        assert {"match": {"chunkText": {"query": "M4+", "boost": 3.0}}} in should
        assert {"match": {"chunkText": {"query": "A类城市", "boost": 2.0}}} in should

    def test_tenant_filter(self):
        q = KeywordRetrievalChannel._build_es_query("q", make_sub_question(tenant_id="租户A"), 10)
        assert {"term": {"tenantId": "租户A"}} in q["query"]["bool"]["filter"]

    def test_empty_tenant_falls_back_to_default(self):
        """tenant_id 缺失时必须 fail-closed 到 default，而不是跨租户检索。"""
        q = KeywordRetrievalChannel._build_es_query("q", make_sub_question(tenant_id=""), 10)
        assert {"term": {"tenantId": "default"}} in q["query"]["bool"]["filter"]

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

    def test_section_path_match_phrase(self):
        q = KeywordRetrievalChannel._build_es_query(
            "q", make_sub_question(section_path="第一章 概述"), 10
        )
        assert {"match_phrase": {"sectionPath": "第一章 概述"}} in q["query"]["bool"]["filter"]

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
                    {"match_phrase": {"documentName": "部署"}},
                    {"match_phrase": {"documentName": "配置"}},
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


class TestQueryLooseningConfig:
    """P0-4：关键词通道候选池过小的两个可调点，都必须能被配置开关控制。"""

    def test_minimum_should_match_defaults_to_strict(self):
        q = KeywordRetrievalChannel._build_es_query("查询词", make_sub_question(), 10)
        mm = [
            c["multi_match"]["minimum_should_match"]
            for c in q["query"]["bool"]["should"]
            if "multi_match" in c
        ]
        assert mm == ["1<30%"]

    def test_minimum_should_match_follows_setting(self, monkeypatch):
        monkeypatch.setattr(
            keyword_module.settings.rag, "keyword_minimum_should_match", "2", raising=False
        )
        q = KeywordRetrievalChannel._build_es_query("查询词", make_sub_question(), 10)
        mm = [
            c["multi_match"]["minimum_should_match"]
            for c in q["query"]["bool"]["should"]
            if "multi_match" in c
        ]
        assert mm == ["2"]

    def test_term_expansion_disabled_by_default(self):
        q = KeywordRetrievalChannel._build_es_query(
            "试用期时长是如何确定的", make_sub_question(), 10
        )
        # Task 4 起基础查询只有 1 条 multi_match；词扩充开启时会多出若干 match 子句
        assert len(q["query"]["bool"]["should"]) == 1

    def test_term_expansion_adds_jieba_terms(self, monkeypatch):
        monkeypatch.setattr(
            keyword_module.settings.rag, "keyword_term_expansion_enabled", True, raising=False
        )
        q = KeywordRetrievalChannel._build_es_query(
            "试用期时长是如何确定的", make_sub_question(), 10
        )
        should = q["query"]["bool"]["should"]
        assert len(should) > 4
        added = [c for c in should if "match" in c and "chunkText" in c["match"]]
        assert added, "应注入 chunkText 词项 should 子句"
        assert all(len(c["match"]["chunkText"]["query"]) >= 2 for c in added)


class TestBuildFallbackSql:
    def test_basic_structure(self):
        sql, args = KeywordRetrievalChannel._build_fallback_sql(
            ["配置", "连接"], make_sub_question(), 10
        )
        assert "pipeline_rag_document_embedding" in sql
        assert "AS similarity" in sql
        assert args[:2] == ["%配置%", "%连接%"]
        assert sql.endswith("LIMIT $4")

    def test_weight_decay(self):
        sql, _ = KeywordRetrievalChannel._build_fallback_sql(
            ["a", "b", "c", "d", "e", "f", "g"], make_sub_question(), 10
        )
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


class TestEvidenceMetadata:
    """ES / PG 降级两条路径都必须把文档层级元数据落到 Evidence。"""

    @pytest.mark.asyncio
    async def test_hits_map_section_and_document(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                return {
                    "hits": {
                        "hits": [
                            {
                                "_score": 3.1,
                                "_source": {
                                    "chunkId": "c1",
                                    "chunkText": "正文",
                                    "sectionPath": "1. 总则 > 1.2 试用期",
                                    "documentName": "员工手册",
                                    "documentId": "9",
                                },
                            }
                        ]
                    }
                }

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        results = await KeywordRetrievalChannel().retrieve(make_sub_question())
        ev = results[0]
        assert ev.document_name == "员工手册"
        assert ev.section_path == "1. 总则 > 1.2 试用期"
        assert ev.section_title == "1.2 试用期"

    @pytest.mark.asyncio
    async def test_fallback_maps_section_and_document(self, monkeypatch):
        class FakeEs:
            async def search(self, index=None, body=None):
                return {"hits": {"hits": []}}

        async def fake_fetch(sql, *args):
            return [
                {
                    "chunk_id": 1,
                    "chunk_text": "正文",
                    "section_path": "2. 报销 > 2.3 住宿标准",
                    "document_id": 5,
                    "document_name": "差旅制度",
                    "similarity": 0.8,
                }
            ]

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        results = await KeywordRetrievalChannel().retrieve(make_sub_question(text="配置数据库连接"))
        ev = results[0]
        assert ev.document_name == "差旅制度"
        assert ev.section_path == "2. 报销 > 2.3 住宿标准"
        assert ev.section_title == "2.3 住宿标准"


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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=1000)),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=1000)),
        )
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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=0)),
        )
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
                {
                    "chunk_id": 1,
                    "chunk_text": "正文",
                    "section_path": "第一章",
                    "document_id": 5,
                    "document_name": "手册",
                    "similarity": 0.8,
                }
            ]

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
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

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(rag=types.SimpleNamespace(keyword_top_k=20)),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: FakeEs())
        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        channel = KeywordRetrievalChannel()
        assert await channel.retrieve(make_sub_question(text="配置数据库")) == []


class TestZeroHitFallback:
    """ES 零命中时是否回退 PG 全表 LIKE，必须是显式开关（默认保行为）。"""

    @pytest.mark.asyncio
    async def test_fallback_skipped_when_disabled(self, monkeypatch):
        import app.rag.channels.keyword as keyword_module
        from app.rag.channels.keyword import KeywordRetrievalChannel

        class _FakeEs:
            async def search(self, index, body):
                return {"hits": {"hits": []}}

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(
                rag=types.SimpleNamespace(
                    keyword_top_k=50,
                    max_channel_top_k=50,
                    keyword_minimum_should_match="1<50%",
                    keyword_term_expansion_enabled=False,
                    keyword_pg_fallback_enabled=False,
                )
            ),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: _FakeEs())

        called = {"fallback": False}

        async def _fail(*args, **kwargs):
            called["fallback"] = True
            return []

        channel = KeywordRetrievalChannel()
        monkeypatch.setattr(channel, "_fallback_pgvector", _fail)

        evidences = await channel.retrieve(make_sub_question(text="问题"))
        assert evidences == []
        assert called["fallback"] is False

    @pytest.mark.asyncio
    async def test_fallback_runs_by_default(self, monkeypatch):
        import app.rag.channels.keyword as keyword_module
        from app.rag.channels.keyword import KeywordRetrievalChannel

        class _FakeEs:
            async def search(self, index, body):
                return {"hits": {"hits": []}}

        monkeypatch.setattr(
            keyword_module,
            "settings",
            types.SimpleNamespace(
                rag=types.SimpleNamespace(
                    keyword_top_k=50,
                    max_channel_top_k=50,
                    keyword_minimum_should_match="1<50%",
                    keyword_term_expansion_enabled=False,
                )
            ),
        )
        monkeypatch.setattr(keyword_module, "get_es", lambda: _FakeEs())

        called = {"fallback": False}

        async def _fallback(*args, **kwargs):
            called["fallback"] = True
            return []

        channel = KeywordRetrievalChannel()
        monkeypatch.setattr(channel, "_fallback_pgvector", _fallback)

        await channel.retrieve(make_sub_question(text="问题"))
        assert called["fallback"] is True


class TestQueryConstruction:
    """Task 4：查询文本必须用干净问句，结构化 token 走独立子句。"""

    async def test_retrieve_uses_clean_question_not_augmented_retrieval_query(
        self, monkeypatch
    ):
        import json

        captured: dict = {}

        class _FakeES:
            async def search(self, index=None, body=None, **kwargs):
                captured["body"] = body
                return {"hits": {"hits": []}}

        monkeypatch.setattr(keyword_module, "get_es", lambda: _FakeES())
        monkeypatch.setattr(
            keyword_module.settings.rag, "keyword_pg_fallback_enabled", False, raising=False
        )
        sub = SubQuestion(
            index=0,
            text="第9条规定了什么",
            retrieval_query="第9条规定了什么 规定 什么 第 九条",
            tenant_id="t1",
        )
        await KeywordRetrievalChannel().retrieve(sub)
        dumped = json.dumps(captured["body"], ensure_ascii=False)
        assert "规定 什么 第" not in dumped
        assert "第9条规定了什么" in dumped

    async def test_retrieve_can_fall_back_to_retrieval_query(self, monkeypatch):
        import json

        captured: dict = {}

        class _FakeES:
            async def search(self, index=None, body=None, **kwargs):
                captured["body"] = body
                return {"hits": {"hits": []}}

        monkeypatch.setattr(keyword_module, "get_es", lambda: _FakeES())
        monkeypatch.setattr(
            keyword_module.settings.rag, "keyword_query_source", "retrieval_query", raising=False
        )
        monkeypatch.setattr(
            keyword_module.settings.rag, "keyword_pg_fallback_enabled", False, raising=False
        )
        sub = SubQuestion(index=0, text="那这个呢", retrieval_query="试用期时长 试用期", tenant_id="t1")
        await KeywordRetrievalChannel().retrieve(sub)
        assert "试用期时长" in json.dumps(captured["body"], ensure_ascii=False)


class TestStructuredTermClauses:
    """Task 5：编号类精确值必须以 term 命中派生 keyword 字段。"""

    def test_clause_token_queries_clause_number_field(self):
        q = KeywordRetrievalChannel._build_es_query(
            "第九条 住宿费用限额", make_sub_question(), 10
        )
        should = q["query"]["bool"]["should"]
        assert {"term": {"clauseNumber": {"value": "9", "boost": 10.0}}} in should

    def test_subclause_grade_city_doc_terms(self):
        q = KeywordRetrievalChannel._build_es_query(
            "《差旅管理制度》9.1 总监级 M4+ A类城市", make_sub_question(), 10
        )
        should = q["query"]["bool"]["should"]
        assert {"term": {"subClauseNumbers": {"value": "9.1", "boost": 8.0}}} in should
        assert {
            "term": {"docNameKeyword": {"value": "差旅管理制度", "boost": 6.0}}
        } in should
        assert {"term": {"gradeCodes": {"value": "M4+", "boost": 4.0}}} in should
        assert {"term": {"cityClasses": {"value": "A", "boost": 3.0}}} in should

    def test_no_term_clauses_without_structured_tokens(self):
        q = KeywordRetrievalChannel._build_es_query("试用期时长如何确定", make_sub_question(), 10)
        should = q["query"]["bool"]["should"]
        assert not any("term" in clause for clause in should)
