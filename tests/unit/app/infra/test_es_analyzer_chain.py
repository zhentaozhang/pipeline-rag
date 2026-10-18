"""ES 分词器降级链（P0-4）：IK 缺失时必须退到 cjk 二元组，而不是 standard 单字。

背景：容器里没装 IK 插件，`_ensure_chunk_index` 捕获异常后建成 standard 分词索引，
中文被切成单字 —— 关键词通道实际退化为"字符重叠"搜索，`match_phrase` 几乎不可能命中。
`cjk` 是 ES 内建 analyzer（cjk_bigram），不依赖插件，是这里唯一正确的降级档位。
"""

from __future__ import annotations

from app.infra.es import _analyzer_chain, _build_chunk_mapping


class TestAnalyzerChain:
    def test_ik_first_then_cjk_then_standard(self):
        chain = _analyzer_chain("ik_max_word", "ik_smart")
        assert chain == [
            ("ik_max_word", "ik_smart"),
            ("cjk", "cjk"),
            ("standard", "standard"),
        ]

    def test_cjk_preferred_skips_ik_but_keeps_standard_tail(self):
        assert _analyzer_chain("cjk", "cjk") == [("cjk", "cjk"), ("standard", "standard")]

    def test_standard_is_terminal(self):
        assert _analyzer_chain("standard", "standard") == [("standard", "standard")]

    def test_empty_preference_falls_back(self):
        assert _analyzer_chain("", "")[0] == ("cjk", "cjk")

    def test_duplicates_are_removed(self):
        chain = _analyzer_chain("cjk", "standard")
        assert len(chain) == len(set(chain))


class TestChunkMapping:
    def test_cjk_mapping_has_no_ik_custom_analyzers(self):
        mapping = _build_chunk_mapping("cjk", "cjk")
        assert "settings" not in mapping or not mapping["settings"]
        props = mapping["mappings"]["properties"]
        for field in ("chunkText", "sectionPath", "documentName", "knowledgeScopeName"):
            assert props[field]["analyzer"] == "cjk"
            assert props[field]["search_analyzer"] == "cjk"

    def test_ik_mapping_registers_custom_analyzers(self):
        mapping = _build_chunk_mapping("ik_max_word", "ik_smart")
        analyzers = mapping["settings"]["analysis"]["analyzer"]
        assert analyzers["ik_max_word_analyzer"]["tokenizer"] == "ik_max_word"
        assert mapping["mappings"]["properties"]["chunkText"]["analyzer"] == "ik_max_word"

    def test_keyword_fields_stay_unanalyzed(self):
        props = _build_chunk_mapping("cjk", "cjk")["mappings"]["properties"]
        for field in ("chunkId", "tenantId", "canonicalPath", "businessCategory"):
            assert props[field]["type"] == "keyword"
