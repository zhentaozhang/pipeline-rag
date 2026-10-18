"""派生 keyword 字段：编号类精确值必须以 keyword 类型落库，才能用 term 精确命中。"""

from app.infra.es import _build_chunk_mapping

DERIVED_FIELDS = (
    "clauseNumber",
    "subClauseNumbers",
    "docNameKeyword",
    "gradeCodes",
    "cityClasses",
)


def test_mapping_has_derived_keyword_fields():
    props = _build_chunk_mapping("ik_max_word", "ik_smart")["mappings"]["properties"]
    for name in DERIVED_FIELDS:
        assert props[name]["type"] == "keyword", name


def test_mapping_declares_lowercase_normalizer():
    mapping = _build_chunk_mapping("ik_max_word", "ik_smart")
    analysis = mapping["settings"]["analysis"]
    assert analysis["normalizer"]["lowercase"] == {"type": "custom", "filter": ["lowercase"]}
    assert mapping["mappings"]["properties"]["docNameKeyword"]["normalizer"] == "lowercase"


def test_mapping_without_ik_keeps_normalizer_but_no_ik_analyzers():
    """standard/cjk 集群也要有 normalizer，否则 docNameKeyword 写入会失败。"""
    mapping = _build_chunk_mapping("cjk", "cjk")
    assert "normalizer" in mapping["settings"]["analysis"]
    assert "ik_smart_analyzer" not in mapping["settings"]["analysis"].get("analyzer", {})
