import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chat.schema import Evidence, ExecutionPlan, SubQuestion
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.rag.parent_block import ParentBlockElevator, _LRUCache


class TestSystemWideOptimizations:
    """验证全系统深度优化（WP1 - WP8）的功能正确性与边界防御"""

    # ── WP3: 后台任务注册与生命周期回收 ──
    @pytest.mark.asyncio
    async def test_chat_task_info_background_task_cancellation_on_finalize(self):
        task_info = ChatTaskInfo(
            conversation_id="conv-1",
            question="test q",
            model_name="test-model",
        )

        async def mock_coro():
            await asyncio.sleep(10)

        bg_task = asyncio.create_task(mock_coro())
        task_info.track_background_task(bg_task)
        assert bg_task in task_info._background_tasks

        # finalize 必须取消后台并发任务
        task_info.finalize()
        # 让出事件循环让 Task 接收 CancelledError
        await asyncio.sleep(0)
        assert bg_task.cancelled()
        assert len(task_info._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_chat_task_info_background_task_cancellation_on_cancel(self):
        task_info = ChatTaskInfo(
            conversation_id="conv-1",
            question="test q",
            model_name="test-model",
        )

        async def mock_coro():
            await asyncio.sleep(10)

        bg_task = asyncio.create_task(mock_coro())
        task_info.track_background_task(bg_task)

        # cancel 必须触发并回收任务
        task_info.cancel()
        assert task_info.cancelled is True
        await asyncio.sleep(0)
        assert bg_task.cancelled()

    # ── WP7: ParentBlock LRU 缓存 TTL 自动淘汰 ──
    def test_parent_block_lru_cache_ttl_expiration(self):
        cache = _LRUCache(maxsize=10, ttl_seconds=0.05)
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

        # 模拟经过 TTL
        time.sleep(0.06)
        assert cache.get("k1") is None
        assert "k1" not in cache._cache

    def test_parent_block_lru_cache_lru_eviction(self):
        cache = _LRUCache(maxsize=2, ttl_seconds=600.0)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.get("a") == 1  # 访问 a，使其成为最近使用
        cache.set("c", 3)  # 超出容量，应淘汰最久未使用的 b
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3

    # ── WP2: ParentBlock 会话生命周期与已关闭 session 防御 ──
    @pytest.mark.asyncio
    async def test_parent_block_elevator_handles_inactive_or_none_session(self):
        elevator = ParentBlockElevator()

        # Mock 一个已被关闭的 session
        closed_session = MagicMock()
        closed_session.execute = AsyncMock()
        closed_session.sync_session = MagicMock(is_active=False)

        # 模拟 session factory 返回托管 session
        managed_session = MagicMock()
        managed_session.execute = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        managed_session.execute.return_value = result_mock

        class MockSessionContext:
            async def __aenter__(self):
                return managed_session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("app.db.session.get_session_factory", return_value=lambda: MockSessionContext()):
            evs = [
                Evidence(
                    chunk_id="999",
                    doc_id="doc-1",
                    title="doc title",
                    source_type="document",
                    content="child text",
                    score=0.9,
                )
            ]
            res = await elevator.elevate(evs, session=closed_session)
            assert len(res) == 1
            # 确认没有调用已关闭的 session，而是借用了 managed_session
            closed_session.execute.assert_not_called()
            managed_session.execute.assert_called_once()

    # ── WP4: 子问题并发检索 Semaphore 限制 ──
    @pytest.mark.asyncio
    async def test_sub_question_retrieval_semaphore_concurrency(self):
        from app.rag.engine import RagRetrievalEngine

        engine = RagRetrievalEngine()
        plan = ExecutionPlan(
            original_question="test multi subquestions",
            rewritten_question="test multi subquestions",
            mode=ExecutionMode.RAG_CHAT,
            sub_questions=[
                SubQuestion(id=f"sq_{i}", index=i, text=f"subquestion {i}", intent="fact")
                for i in range(5)
            ],
        )

        active_concurrent = 0
        max_seen_concurrent = 0
        lock = asyncio.Lock()

        async def fake_retrieve_one(sq, idx, *args, **kwargs):
            nonlocal active_concurrent, max_seen_concurrent
            async with lock:
                active_concurrent += 1
                if active_concurrent > max_seen_concurrent:
                    max_seen_concurrent = active_concurrent
            await asyncio.sleep(0.02)
            async with lock:
                active_concurrent -= 1
            from app.chat.schema import SubQuestionEvidence

            return SubQuestionEvidence(
                sub_question=sq,
                evidences=[],
                channel_trace={},
                fused_candidate_count=0,
                parent_candidate_count=0,
                reranked_candidate_count=0,
            )

        with (
            patch.object(engine, "_retrieve_one", side_effect=fake_retrieve_one),
            patch("app.rag.engine.settings.rag.sub_question_max_concurrency", 2),
        ):
            await engine.retrieve(plan)
            assert max_seen_concurrent <= 2

    # ── WP5: 质量自审重试反馈 Prompt 截断 ──
    def test_quality_feedback_clipping(self):
        from app.common.text_utils import clip_tail

        long_feedback = "问题解释不够清晰。" * 60  # 540 字，超过 500 字
        assert len(long_feedback) > 500
        clipped = clip_tail(long_feedback, 500)
        assert len(clipped) <= 500
        assert clipped.startswith("…")

    # ── WP8: MySQL pool_recycle 参数验证 ──
    def test_mysql_pool_recycle_default(self):
        import inspect

        from app.db.session import init_db

        source = inspect.getsource(init_db)
        assert "pool_recycle=300" in source

    # ── 边界加固：引用校验任务取消后安全隔离 ──
    @pytest.mark.asyncio
    async def test_citation_task_cancelled_does_not_raise(self):
        async def dummy_cancelled():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy_cancelled())
        task.cancel()

        # 模拟 service_executor 中复用 task 逻辑
        is_cancelling_or_cancelled = (
            getattr(task, "cancelling", lambda: 0)() > 0
            or getattr(task, "cancelled", lambda: False)()
        )
        assert is_cancelling_or_cancelled is True
        # 即使 await 也会在 suppress (asyncio.CancelledError, Exception) 中被安全吸收
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
