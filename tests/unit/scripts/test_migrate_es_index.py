"""索引迁移脚本的纯函数契约。"""

import pytest

from scripts.evaluation.migrate_es_index import build_target_mapping, verify_migration


def test_target_mapping_uses_ik_analyzers():
    mapping = build_target_mapping("ik_max_word", "ik_smart")
    props = mapping["mappings"]["properties"]
    assert props["chunkText"]["analyzer"] == "ik_max_word"
    assert props["chunkText"]["search_analyzer"] == "ik_smart"
    assert (
        mapping["settings"]["analysis"]["analyzer"]["ik_smart_analyzer"]["tokenizer"] == "ik_smart"
    )


def test_verify_migration_raises_on_count_mismatch():
    with pytest.raises(ValueError) as exc:
        verify_migration(source_count=305, target_count=304)
    assert "304" in str(exc.value) and "305" in str(exc.value)


def test_verify_migration_returns_summary_on_match():
    assert verify_migration(source_count=305, target_count=305) == {
        "source": 305,
        "target": 305,
        "matched": True,
    }
