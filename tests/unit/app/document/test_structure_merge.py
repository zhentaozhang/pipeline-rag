"""P0-2 粒度校准：结构节点合并的纯逻辑测试（无 DB / 无网络）。"""

import types

import pytest

from app.config import get_settings
from app.document.chunker import structure as structure_mod
from app.document.chunker.config import ChunkConfig
from app.document.chunker.structure import StructureChunker


def cand(text):
    return types.SimpleNamespace(content_text=text)


@pytest.fixture
def fake_tokens(monkeypatch):
    # 让 token 数 == 字符数，便于构造确定性用例
    monkeypatch.setattr(structure_mod, "count_tokens", lambda s: len(s))


class TestMergeGroups:
    def test_flushes_at_target(self, fake_tokens):
        nodes = [cand("aaaa"), cand("bbbb"), cand("cccc"), cand("dddd"), cand("eeee")]
        groups = StructureChunker._merge_groups(nodes, target_tokens=10, max_tokens=100)
        assert [[n.content_text for n in g] for g in groups] == [
            ["aaaa", "bbbb", "cccc"],
            ["dddd", "eeee"],
        ]

    def test_flushes_before_exceeding_max(self, fake_tokens):
        nodes = [cand("aaaaaa"), cand("bbbbbb")]
        groups = StructureChunker._merge_groups(nodes, target_tokens=1000, max_tokens=10)
        assert [[n.content_text for n in g] for g in groups] == [["aaaaaa"], ["bbbbbb"]]

    def test_oversized_single_node_stays_alone(self, fake_tokens):
        nodes = [cand("x" * 50)]
        groups = StructureChunker._merge_groups(nodes, target_tokens=10, max_tokens=10)
        assert len(groups) == 1 and len(groups[0]) == 1

    def test_empty_input(self, fake_tokens):
        assert StructureChunker._merge_groups([], target_tokens=10, max_tokens=20) == []

    def test_merges_adjacent_small_nodes(self, fake_tokens):
        nodes = [cand("aa"), cand("bb"), cand("cc")]
        groups = StructureChunker._merge_groups(nodes, target_tokens=100, max_tokens=100)
        assert len(groups) == 1 and len(groups[0]) == 3


class TestDefaultsAreOff:
    def test_chunk_config_default_off(self):
        assert ChunkConfig().merge_small_sections is False

    def test_settings_default_off(self):
        c = get_settings().chunk
        assert c.merge_small_sections_enabled is False
        assert c.merge_target_tokens == 320
        assert c.merge_max_tokens == 512
