"""ParallelExecutor 纯逻辑测试：拓扑分层 + 空计划/循环依赖执行路径。"""

import pytest

from app.chat.schema import ExecutionPlan, SubPlan
from app.common.enums import ExecutionMode
from app.executors.parallel_executor import _topological_layers


def _sp(id: str, depends_on: list[str] | None = None) -> SubPlan:
    return SubPlan(id=id, mode=ExecutionMode.RAG_CHAT, question=f"问题{id}", depends_on=depends_on or [])


class TestTopologicalLayers:
    def test_no_dependency_single_layer(self):
        plans = [_sp("a"), _sp("b"), _sp("c")]
        layers = _topological_layers(plans)
        assert len(layers) == 1
        assert {sp.id for sp in layers[0]} == {"a", "b", "c"}

    def test_chain_dependency_produces_ordered_layers(self):
        plans = [_sp("a"), _sp("b", ["a"]), _sp("c", ["b"])]
        layers = _topological_layers(plans)
        assert [sp.id for sp in layers[0]] == ["a"]
        assert [sp.id for sp in layers[1]] == ["b"]
        assert [sp.id for sp in layers[2]] == ["c"]

    def test_diamond_dependency(self):
        plans = [_sp("a"), _sp("b", ["a"]), _sp("c", ["a"]), _sp("d", ["b", "c"])]
        layers = _topological_layers(plans)
        assert len(layers) == 3
        assert {sp.id for sp in layers[0]} == {"a"}
        assert {sp.id for sp in layers[1]} == {"b", "c"}
        assert {sp.id for sp in layers[2]} == {"d"}

    def test_cyclic_dependency_raises_value_error(self):
        plans = [_sp("a", ["b"]), _sp("b", ["a"])]
        with pytest.raises(ValueError, match="循环依赖"):
            _topological_layers(plans)

    def test_orphan_node_raises_value_error(self):
        plans = [_sp("a", ["missing"])]
        with pytest.raises(ValueError, match="循环依赖或孤立节点"):
            _topological_layers(plans)

    def test_empty_list_returns_empty(self):
        assert _topological_layers([]) == []


class TestExecuteEmptyPlan:
    async def test_empty_sub_plans_emits_noop_text(self):
        from app.chat.task_info import ChatTaskInfo
        from app.executors.parallel_executor import ParallelExecutor

        task = ChatTaskInfo(conversation_id="conv-1", question="q")
        executor = ParallelExecutor(db=None, task=task, registry=None)

        chunks = [chunk async for chunk in executor.execute(ExecutionPlan(
            mode=ExecutionMode.MULTI_AGENT,
            original_question="q",
            rewritten_question="q",
        ))]

        assert len(chunks) == 1
        assert "无需并行处理" in chunks[0]
        assert "data: " in chunks[0]

    async def test_cyclic_dependency_emits_error_event_without_workers(self):
        from app.chat.task_info import ChatTaskInfo
        from app.executors.parallel_executor import ParallelExecutor

        task = ChatTaskInfo(conversation_id="conv-2", question="q")
        executor = ParallelExecutor(db=None, task=task, registry=None)

        plan = ExecutionPlan(
            mode=ExecutionMode.MULTI_AGENT,
            original_question="q",
            rewritten_question="q",
            sub_plans=[_sp("a", ["b"]), _sp("b", ["a"])],
        )

        chunks = [chunk async for chunk in executor.execute(plan)]

        assert any("循环依赖" in c for c in chunks)
        assert not any("正在并行处理" in c for c in chunks)
