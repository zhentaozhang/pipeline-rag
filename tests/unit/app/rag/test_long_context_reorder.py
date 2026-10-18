"""P2-7 LongContextReorder：纯函数 + 组装侧接入（默认关）。"""

from app.chat.schema import Evidence
from app.config import get_settings
from app.rag.assembly import PromptAssemblyService, PromptBudget
from app.rag.reorder import reorder_long_context


class TestReorderLongContext:
    def test_short_lists_unchanged(self):
        assert reorder_long_context([]) == []
        assert reorder_long_context(["a"]) == ["a"]
        assert reorder_long_context(["a", "b"]) == ["a", "b"]

    def test_even_length(self):
        # 相关度降序 [0..5] → 首尾强相关、中部弱相关
        assert reorder_long_context([0, 1, 2, 3, 4, 5]) == [0, 2, 4, 5, 3, 1]

    def test_odd_length(self):
        assert reorder_long_context([0, 1, 2, 3, 4]) == [0, 2, 4, 3, 1]

    def test_best_at_head_second_at_tail_worst_in_middle(self):
        d = list(range(8))
        out = reorder_long_context(d)
        assert out[0] == 0  # 最相关在首
        assert out[-1] == 1  # 次相关在尾
        # 最不相关的两个（7、6）落在中部
        mid = out[len(out) // 2 - 1 : len(out) // 2 + 1]
        assert 7 in mid and 6 in mid

    def test_no_duplicates_or_loss(self):
        d = list(range(7))
        assert sorted(reorder_long_context(d)) == d


def _ev(cid, ref):
    return Evidence(
        chunk_id=cid,
        doc_id="d1",
        title="文档",
        content="x" * 50,
        source_type="document",
        reference_id=ref,
        section_title="1.1",
    )


def _order(rendered: str) -> list[str]:
    import re

    return re.findall(r"\[(\d+)\]", rendered)


class TestAssemblyWiring:
    def test_disabled_keeps_relevance_order(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "long_context_reorder_enabled", False)
        evs = [_ev(f"c{i}", i + 1) for i in range(6)]
        out = PromptAssemblyService()._append_references(evs, set(), PromptBudget(10**6, 10**6))
        assert _order(out) == ["1", "2", "3", "4", "5", "6"]

    def test_enabled_reorders(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "long_context_reorder_enabled", True)
        evs = [_ev(f"c{i}", i + 1) for i in range(6)]
        out = PromptAssemblyService()._append_references(evs, set(), PromptBudget(10**6, 10**6))
        assert _order(out) == ["1", "3", "5", "6", "4", "2"]

    def test_enabled_but_tight_budget_falls_back(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "long_context_reorder_enabled", True)
        evs = [_ev(f"c{i}", i + 1) for i in range(6)]
        # 预算不足以放下整组（~432 字符）：必须保持原序，让被截断的是最不相关项
        out = PromptAssemblyService()._append_references(evs, set(), PromptBudget(300, 300))
        assert _order(out)[:3] == ["1", "2", "3"]

    def test_two_evidences_not_reordered(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "long_context_reorder_enabled", True)
        evs = [_ev("c0", 1), _ev("c1", 2)]
        out = PromptAssemblyService()._append_references(evs, set(), PromptBudget(10**6, 10**6))
        assert _order(out) == ["1", "2"]


class TestConfigDefault:
    def test_default_off(self):
        assert get_settings().rag.long_context_reorder_enabled is False
