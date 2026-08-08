"""executors 注册表与 Clarification/Refusal 执行器测试（纯 SSE 生成，无 DB/LLM）。"""

import json

import pytest

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.executors.clarification import ClarificationExecutor
from app.executors.refusal import RefusalExecutor
from app.executors.registry import ExecutorRegistry, _build_default_registry


def _task() -> ChatTaskInfo:
    return ChatTaskInfo(conversation_id="c1", question="q", exchange_id=5)


def _parse_events(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: ") :].strip()) for c in chunks]


class TestBuildDefaultRegistry:
    def test_maps_six_modes(self):
        reg = _build_default_registry()
        assert set(reg) == {
            ExecutionMode.CLARIFICATION,
            ExecutionMode.RETRIEVAL,
            ExecutionMode.REACT_AGENT,
            ExecutionMode.GRAPH_ONLY,
            ExecutionMode.GRAPH_THEN_EVIDENCE,
            ExecutionMode.REFUSAL,
        }
        assert reg[ExecutionMode.CLARIFICATION] is ClarificationExecutor
        assert reg[ExecutionMode.REFUSAL] is RefusalExecutor


class TestRegistryGet:
    def test_unknown_mode_raises(self):
        reg = ExecutorRegistry(db=None, task=_task())
        with pytest.raises(RuntimeError, match="未找到执行模式"):
            reg.get(ExecutionMode.OPEN_CHAT)

    def test_clarification_instantiated_with_task(self):
        task = _task()
        executor = ExecutorRegistry(db=None, task=task).get(ExecutionMode.CLARIFICATION)
        assert isinstance(executor, ClarificationExecutor)
        assert executor.task is task

    def test_refusal_instantiated_with_task(self):
        task = _task()
        executor = ExecutorRegistry(db=None, task=task).get(ExecutionMode.REFUSAL)
        assert isinstance(executor, RefusalExecutor)


class TestClarificationExecutor:
    @pytest.mark.asyncio
    async def test_default_reply_when_plan_none(self):
        task = _task()
        chunks = [c async for c in ClarificationExecutor(task).execute(None)]
        events = _parse_events(chunks)
        types = [e["type"] for e in events]
        assert types[0] == "thinking"
        assert events[-1]["type"] == "text"
        assert "无法稳定判断" in events[-1]["content"]
        assert task.thinking_steps[0] == "当前问题涉及多份候选文档，先向你确认知识范围。"

    @pytest.mark.asyncio
    async def test_uses_plan_reply_when_provided(self):
        plan = ExecutionPlan(
            mode=ExecutionMode.CLARIFICATION,
            original_question="q",
            rewritten_question="q",
            clarification_reply="请选择文档 A 或 B",
            clarification_options=["A", "B"],
        )
        chunks = [c async for c in ClarificationExecutor(_task()).execute(plan)]
        events = _parse_events(chunks)
        assert events[-1]["content"] == "请选择文档 A 或 B"

    @pytest.mark.asyncio
    async def test_plan_without_reply_falls_back_to_default(self):
        plan = ExecutionPlan(mode=ExecutionMode.CLARIFICATION, original_question="q", rewritten_question="q")
        chunks = [c async for c in ClarificationExecutor(_task()).execute(plan)]
        events = _parse_events(chunks)
        assert "无法稳定判断" in events[-1]["content"]

    @pytest.mark.asyncio
    async def test_clarification_reason_emits_status(self):
        plan = ExecutionPlan(
            mode=ExecutionMode.CLARIFICATION,
            original_question="q",
            rewritten_question="q",
            clarification_reason="命中多份候选文档",
        )
        chunks = [c async for c in ClarificationExecutor(_task()).execute(plan)]
        types = [e["type"] for e in _parse_events(chunks)]
        assert "status" in types

    @pytest.mark.asyncio
    async def test_exchange_id_in_events(self):
        chunks = [c async for c in ClarificationExecutor(_task()).execute(None)]
        events = _parse_events(chunks)
        assert all(e["exchangeId"] == 5 for e in events)


class TestRefusalExecutor:
    @pytest.mark.asyncio
    async def test_default_refusal_reply(self):
        task = _task()
        chunks = [c async for c in RefusalExecutor(task).execute(None)]
        events = _parse_events(chunks)
        assert events[0]["type"] == "thinking"
        assert events[-1]["content"] == "根据企业安全规范，我无法回答该问题。"
        assert task.thinking_steps == ["触发安全护栏拦截。"]

    @pytest.mark.asyncio
    async def test_uses_plan_reply_when_provided(self):
        plan = ExecutionPlan(
            mode=ExecutionMode.REFUSAL,
            original_question="q",
            rewritten_question="q",
            refusal_reply="拒绝：违反政策",
        )
        chunks = [c async for c in RefusalExecutor(_task()).execute(plan)]
        events = _parse_events(chunks)
        assert events[-1]["content"] == "拒绝：违反政策"

    @pytest.mark.asyncio
    async def test_plan_without_reply_falls_back(self):
        plan = ExecutionPlan(mode=ExecutionMode.REFUSAL, original_question="q", rewritten_question="q")
        chunks = [c async for c in RefusalExecutor(_task()).execute(plan)]
        events = _parse_events(chunks)
        assert events[-1]["content"] == "根据企业安全规范，我无法回答该问题。"
