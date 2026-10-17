import pytest
from unittest.mock import AsyncMock, MagicMock

from app.chat.schema import Evidence, ExecutionPlan, SubQuestion, SubQuestionEvidence
from app.rag.engine import RagRetrievalEngine, RetrievalChannelResult
from app.rag.parent_block import ParentBlockElevator
from app.rag.assembly import PromptAssemblyService, PromptBudget
from app.chat.citation_verifier import _reference_content, extract_citations


class TestMultiUserAndEngineV2:
    @pytest.mark.asyncio
    async def test_child_rerank_order_and_parent_elevation(self, monkeypatch):
        """测试先对 child 进行重排，再聚合提升为 ParentBlock，并保持 rerank_score 排序"""
        engine = RagRetrievalEngine()

        # 模拟 3 个 child chunks，分属两个 parent
        c1 = Evidence(chunk_id="c1", doc_id="d1", title="Doc1", content="child 1 content", score=0.6)
        c2 = Evidence(chunk_id="c2", doc_id="d1", title="Doc1", content="child 2 content", score=0.8)
        c3 = Evidence(chunk_id="c3", doc_id="d2", title="Doc2", content="child 3 content", score=0.7)

        # 模拟 rerank
        async def fake_rerank(query, candidates):
            # 将 c1 打高分 0.95，c2 打 0.50，c3 打 0.85
            for c in candidates:
                if c.chunk_id == "c1":
                    c.rerank_score = 0.95
                elif c.chunk_id == "c2":
                    c.rerank_score = 0.50
                elif c.chunk_id == "c3":
                    c.rerank_score = 0.85
            return sorted(candidates, key=lambda x: x.rerank_score, reverse=True)

        monkeypatch.setattr(engine, "_maybe_rerank", fake_rerank)

        # 模拟 ParentBlockElevator: c1 & c2 属于 parent P1, c3 属于 parent P2
        elevator = ParentBlockElevator()
        monkeypatch.setattr(
            "app.rag.parent_block._CHUNK_PARENT_CACHE.get",
            lambda cid: "p1" if cid in ("c1", "c2") else "p2",
        )
        monkeypatch.setattr(
            "app.rag.parent_block._PARENT_CONTENT_CACHE.get",
            lambda pid: {"text": f"Parent full text for {pid}", "path": "Sec1"},
        )

        candidates = [c1, c2, c3]
        reranked = await engine._maybe_rerank("test query", candidates)
        filtered = engine._apply_rerank_filter(reranked)

        elevated = await elevator.elevate(filtered)

        # 校验：
        # 1. P1 聚合时选中的 best_child 应该是 rerank_score 更高的 c1 (0.95)，而非初始 score 更高的 c2 (0.8)
        p1_doc = next(e for e in elevated if e.parent_block_id == 0 or e.chunk_id in ("c1", "c2"))
        assert p1_doc.chunk_id == "c1"
        assert p1_doc.child_chunk_id == "c1"
        assert p1_doc.child_chunk_text == "child 1 content"
        assert "Parent full text for p1" in p1_doc.content

        # 2. elevated 顺序应保持 c1 (0.95) 在 c3 (0.85) 前面
        assert elevated[0].chunk_id == "c1"
        assert elevated[1].chunk_id == "c3"

    def test_vector_gate_near_miss_fallback(self, monkeypatch):
        """测试全部低于硬阈值但最高分落在 85% 软门限内的近邻兜底保留"""
        from app.config import get_settings

        engine = RagRetrievalEngine()
        settings = get_settings()
        monkeypatch.setattr(settings.rag, "min_vector_similarity", 0.50)

        # 场景 1: 分数 0.45 (>= 0.50 * 0.85 = 0.425)，触发软兜底
        docs = [
            Evidence(chunk_id="c1", doc_id="d1", title="D1", content="t1", score=0.45, original_score=0.45),
            Evidence(chunk_id="c2", doc_id="d1", title="D1", content="t2", score=0.30, original_score=0.30),
        ]
        result = RetrievalChannelResult(channel_name="vector", documents=docs)
        filtered = engine._apply_evidence_gate(result)
        assert len(filtered.documents) == 1
        assert filtered.documents[0].chunk_id == "c1"
        assert filtered.documents[0].gate_passed is True

        # 场景 2: 分数 0.35 (< 0.425)，不触发兜底，全部过滤
        docs2 = [
            Evidence(chunk_id="c3", doc_id="d1", title="D1", content="t3", score=0.35, original_score=0.35),
        ]
        result2 = RetrievalChannelResult(channel_name="vector", documents=docs2)
        filtered2 = engine._apply_evidence_gate(result2)
        assert len(filtered2.documents) == 0

    def test_citation_verifier_child_chunk_priority(self):
        """测试引用文本提取优先包含 child_chunk_text，且突破 280 限制至 1200"""
        long_body = "第一章 考勤管理规则详细内容。" + ("补充规定描述文本。" * 40) + "试用期离职需提前3天通知，正式员工提前30天通知。"
        ref_entry = {
            "id": 1,
            "title": "员工手册",
            "child_chunk_id": "c101",
            "child_chunk_text": "试用期离职需提前3天通知。",
            "content": long_body,
        }
        extracted = _reference_content(ref_entry, 1, max_chars=1200)
        assert "试用期离职需提前3天通知" in extracted
        assert len(extracted) > 280

    def test_assembly_soft_window_truncation(self):
        """测试当父块超出预算时，以命中子块为核心裁剪软窗口纳入 Prompt"""
        assembler = PromptAssemblyService()
        budget = PromptBudget(total_budget=500, per_sub_question_budget=500)

        child_snippet = "关键核心条款：违规赔偿两倍月薪。"
        long_parent = "背景前言：" + ("无用背景信息。" * 80) + child_snippet + ("后续条款补充。" * 80)

        ev = Evidence(
            chunk_id="c1",
            doc_id="d1",
            title="赔偿协议",
            content=long_parent,
            child_chunk_id="c1",
            child_chunk_text=child_snippet,
            reference_id=1,
            score=0.9,
        )

        rendered_keys = set()
        rendered_text = assembler._append_references([ev], rendered_keys, budget)

        # 验证没有直接整块省略，且成功保留了关键子块内容
        assert child_snippet in rendered_text
        assert "已通过软窗口裁剪纳入 Prompt" in budget.rendered_reference_details[0]
        assert budget.rendered_reference_count == 1
        assert budget.omitted_reference_count == 0
