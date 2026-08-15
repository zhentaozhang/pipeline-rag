"""记忆压缩：版本 CAS 乐观并发 + 50+ 轮长会话回归测试。

覆盖：
- _select_overflow_batches：55 轮会话只压超窗口部分、分批 ≤ batch_size、窗口内保留
- compress_history 的版本 CAS：正常写入递增版本、并发冲突跳过、首次创建版本=1
（FakeSession + fake_llm，不依赖真实 DB）
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.sql.dml import Update

from app.chat.memory_compressor import ConversationMemoryCompressor


def _exchange(eid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid, question=f"问题{eid}", answer=f"回答{eid}", turn_status=2
    )


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None, scalar=None, rowcount=1):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _Scalars(self._rows)


class FakeSession:
    """最小 FakeSession：支持 compress_history 的 execute/add/commit。"""

    def __init__(self, mem=None, exchanges=None, update_rowcount=1):
        self.mem = mem
        self.exchanges = exchanges or []
        self.update_rowcount = update_rowcount
        self.update_calls = 0
        self.committed = 0
        self.added = []

    async def execute(self, stmt):
        if isinstance(stmt, Update):
            self.update_calls += 1
            return _Result(rowcount=self.update_rowcount)
        table_name = ""
        get_final = getattr(stmt, "get_final_froms", None)
        if get_final is not None:
            froms = get_final()
            if froms:
                table_name = getattr(froms[0], "name", "")
        if "memory" in table_name:
            return _Result(scalar=self.mem)
        return _Result(rows=self.exchanges)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1


@pytest.fixture
def compressor() -> ConversationMemoryCompressor:
    return ConversationMemoryCompressor()


def _mem(summary_version=0, summary_json='{"summary": "已有摘要"}') -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conv-1",
        summary_version=summary_version,
        summary_json=summary_json,
        summary_text="已有摘要",
        covered_exchange_id=0,
    )


class TestSelectOverflowBatches:
    def test_55_rounds_only_compresses_overflow(self):
        """55 轮会话、窗口 4：只有最旧 51 轮进摘要，最近 4 轮保留原文。"""
        exchanges = [_exchange(i) for i in range(1, 56)]  # 55 轮
        batches = ConversationMemoryCompressor._select_overflow_batches(exchanges, 4, 6)
        assert sum(len(b) for b in batches) == 51
        assert all(b[-1].id < 52 for b in batches)  # 全部来自最旧 51 轮
        assert batches[0][0].id == 1  # 从最早开始
        assert all(len(b) <= 6 for b in batches)

    def test_batches_are_ordered_and_contiguous(self):
        batches = ConversationMemoryCompressor._select_overflow_batches(
            [_exchange(i) for i in range(1, 56)], 4, 6
        )
        flat = [e.id for b in batches for e in b]
        assert flat == list(range(1, 52))
        assert [len(b) for b in batches] == [6, 6, 6, 6, 6, 6, 6, 6, 3]

    def test_no_overflow_returns_empty(self):
        # 55 轮但窗口 60 → 无溢出
        assert ConversationMemoryCompressor._select_overflow_batches(
            [_exchange(i) for i in range(1, 56)], 60, 6
        ) == []

    def test_window_exact_boundary(self):
        # 恰好窗口大小 → 无溢出（最近 4 轮全部保留）
        assert ConversationMemoryCompressor._select_overflow_batches(
            [_exchange(i) for i in range(1, 5)], 4, 6
        ) == []


class TestCompressVersionCAS:
    @pytest.fixture
    def fifty_five_rounds(self):
        return [_exchange(i) for i in range(1, 56)]

    async def test_normal_write_increments_version(
        self, compressor, fake_llm, fifty_five_rounds, monkeypatch
    ):
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.window_size", 50)
        fake_llm.queue_json({"summary": "合并后摘要"})
        db = FakeSession(mem=_mem(summary_version=3), exchanges=fifty_five_rounds)
        await compressor.compress_history("conv-1", db)
        assert db.update_calls == 1  # CAS 条件更新执行
        assert db.committed == 1

    async def test_cas_conflict_skips_write(
        self, compressor, fake_llm, fifty_five_rounds, monkeypatch
    ):
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.window_size", 50)
        fake_llm.queue_json({"summary": "合并后摘要"})
        db = FakeSession(
            mem=_mem(summary_version=3), exchanges=fifty_five_rounds, update_rowcount=0
        )
        await compressor.compress_history("conv-1", db)
        assert db.update_calls == 1  # CAS 执行了
        assert db.committed == 0  # 冲突 → 放弃，不提交
        assert db.added == []  # 不落新记录

    async def test_first_create_version_starts_at_one(
        self, compressor, fake_llm, fifty_five_rounds, monkeypatch
    ):
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.window_size", 50)
        fake_llm.queue_json({"summary": "首次摘要"})
        db = FakeSession(mem=None, exchanges=fifty_five_rounds)
        await compressor.compress_history("conv-1", db)
        assert len(db.added) == 1
        assert db.added[0].summary_version == 1
        assert db.committed == 1

    async def test_55_rounds_compress_with_llm(
        self, compressor, fake_llm, fifty_five_rounds, monkeypatch
    ):
        """55 轮、窗口 50 → 溢出 5 轮 → 1 批 → 一次 LLM 合并，CAS 写入。"""
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.window_size", 50)
        fake_llm.queue_json({"summary": "55 轮合并摘要"})
        db = FakeSession(mem=_mem(summary_version=0), exchanges=fifty_five_rounds)
        await compressor.compress_history("conv-1", db)
        assert db.update_calls == 1
        assert db.committed == 1
        # LLM 被调用过一次（合并 5 轮 = 1 批）
        assert len(fake_llm.calls) == 1
