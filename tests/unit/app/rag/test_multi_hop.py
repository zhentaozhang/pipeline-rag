"""P3-8 迭代式多跳：循环纯逻辑 + 上下文累积 + 调度（全 fake，无 LLM / 无 DB）。"""

from app.chat.schema import Evidence, SubQuestion, SubQuestionEvidence
from app.config import get_settings
from app.rag.engine import RagRetrievalContext, RagRetrievalEngine
from app.rag.multi_hop import iterate_hops


def make_ev(cid, content="内容", parent=None):
    return Evidence(
        chunk_id=cid,
        title="文档",
        content=content,
        doc_id="d1",
        source_type="document",
        parent_block_id=parent,
    )


def make_ctx(*evidences):
    return RagRetrievalContext(
        retrieval_question="q",
        sub_question_evidence_list=[
            SubQuestionEvidence(
                sub_question=SubQuestion(index=0, text="q"), evidences=list(evidences)
            )
        ],
    )


class TestIterateHops:
    async def test_converges_immediately_on_empty_next(self):
        calls = {"retrieve": 0}

        async def next_q(q, ctx):
            return ""

        async def retrieve(q):
            calls["retrieve"] += 1
            return make_ctx()

        merged = []

        async def merge(a, b):
            merged.append((a, b))
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=3,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 1
        assert calls["retrieve"] == 0
        assert merged == []

    async def test_runs_one_extra_hop_then_converges(self):
        seq = ["下一跳查询", ""]

        async def next_q(q, ctx):
            return seq.pop(0)

        async def retrieve(q):
            assert q == "下一跳查询"
            return make_ctx(make_ev("c2"))

        def merge(a, b):
            a.sub_question_evidence_list.extend(b.sub_question_evidence_list)
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=3,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 2
        assert len(ctx.sub_question_evidence_list) == 2

    async def test_respects_max_hops(self):
        counter = {"n": 0}

        async def next_q(q, ctx):
            counter["n"] += 1
            return f"query-{counter['n']}"

        async def retrieve(q):
            return make_ctx(make_ev(f"c-{q}"))

        def merge(a, b):
            a.sub_question_evidence_list.extend(b.sub_question_evidence_list)
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c0")),
            max_hops=3,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 3

    async def test_repeated_query_stops(self):
        async def next_q(q, ctx):
            return q  # 与上一跳相同

        async def retrieve(q):
            raise AssertionError("不应触发检索")

        async def merge(a, b):
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=5,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 1

    async def test_next_query_error_is_swallowed(self):
        async def next_q(q, ctx):
            raise RuntimeError("llm down")

        async def retrieve(q):
            raise AssertionError("不应触发检索")

        async def merge(a, b):
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=3,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 1

    async def test_retrieve_error_is_swallowed(self):
        async def next_q(q, ctx):
            return "下一跳"

        async def retrieve(q):
            raise RuntimeError("search down")

        async def merge(a, b):
            raise AssertionError("检索失败不应 merge")

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=3,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 1

    async def test_max_hops_one_disables_loop(self):
        async def next_q(q, ctx):
            raise AssertionError("max_hops=1 不应调用 next_query")

        async def retrieve(q):
            raise AssertionError("max_hops=1 不应检索")

        async def merge(a, b):
            return a

        ctx, hops = await iterate_hops(
            "q",
            make_ctx(make_ev("c1")),
            max_hops=1,
            next_query_fn=next_q,
            retrieve_fn=retrieve,
            merge_fn=merge,
        )
        assert hops == 1


class TestMergeContexts:
    def test_dedup_and_union(self):
        engine = RagRetrievalEngine()
        base = make_ctx(make_ev("c1"))
        base.used_channels.add("vector")
        base.retrieval_notes.append("n1")
        extra = make_ctx(make_ev("c1"), make_ev("c2"))
        extra.used_channels.add("keyword")
        extra.retrieval_notes.append("n2")

        merged = engine._merge_contexts(base, extra)

        ids = [ev.chunk_id for se in merged.sub_question_evidence_list for ev in se.evidences]
        assert ids == ["c1", "c2"]  # c1 去重
        assert merged.used_channels == {"vector", "keyword"}
        assert merged.retrieval_notes == ["n1", "n2"]

    def test_reference_ids_reassigned(self):
        engine = RagRetrievalEngine()
        base = make_ctx(make_ev("c1"))
        extra = make_ctx(make_ev("c2"))
        merged = engine._merge_contexts(base, extra)
        refs = [ev.reference_id for se in merged.sub_question_evidence_list for ev in se.evidences]
        assert refs == [1, 2]


class TestDispatch:
    async def test_disabled_uses_plain_corrective_path(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "iterative_multi_hop_enabled", False)
        monkeypatch.setattr(get_settings().rag, "corrective_retrieval_enabled", False)

        async def fake_retrieve(self, plan, tracer=None):
            return make_ctx(make_ev("c1"))

        async def boom(self, plan, tracer=None):
            raise AssertionError("默认关时不应走多跳")

        monkeypatch.setattr(RagRetrievalEngine, "retrieve", fake_retrieve)
        monkeypatch.setattr(RagRetrievalEngine, "retrieve_iterative_multi_hop", boom)

        from app.chat.schema import ExecutionPlan
        from app.common.enums import ExecutionMode

        plan = ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT, original_question="q", rewritten_question="q"
        )
        ctx = await RagRetrievalEngine().retrieve_with_correction(plan)
        assert ctx is not None

    async def test_enabled_dispatches_to_multi_hop(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "iterative_multi_hop_enabled", True)
        calls = []

        async def fake_multi(self, plan, tracer=None):
            calls.append("multi")
            return make_ctx(make_ev("c1"))

        monkeypatch.setattr(RagRetrievalEngine, "retrieve_iterative_multi_hop", fake_multi)

        from app.chat.schema import ExecutionPlan
        from app.common.enums import ExecutionMode

        plan = ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT, original_question="q", rewritten_question="q"
        )
        await RagRetrievalEngine().retrieve_with_correction(plan)
        assert calls == ["multi"]


class TestConfigDefault:
    def test_default_off(self):
        assert get_settings().rag.iterative_multi_hop_enabled is False
        assert get_settings().rag.iterative_multi_hop_max_hops == 2
