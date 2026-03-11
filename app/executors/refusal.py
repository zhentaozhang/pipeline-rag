"""
安全护栏拒答执行器
当 Orchestrator 检测到安全风险或恶意意图时，直接短路返回拒答话术。
"""

from collections.abc import AsyncIterator

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event
from app.executors.base import ConversationExecutor


class RefusalExecutor(ConversationExecutor):
    """当 Orchestrator 意图识别命中护栏时，直接返回拒答信息"""

    mode = ExecutionMode.REFUSAL

    def __init__(self, task: ChatTaskInfo) -> None:
        self.task = task

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        from app.observability import SpanKind

        tracer = self.task.tracer
        conv_id = self.task.conversation_id
        exch_id = self.task.exchange_id

        refusal_reply = (
            "根据企业安全规范，我无法回答该问题。"
            if plan is None
            else (plan.refusal_reply or "根据企业安全规范，我无法回答该问题。")
        )

        yield sse_event(
            SSEEventType.THINKING,
            "触发安全护栏拦截。",
            conversation_id=conv_id,
            exchange_id=exch_id,
        )
        self.task.thinking_steps.append("触发安全护栏拦截。")

        if tracer is not None:
            async with tracer.span("refusal", kind=SpanKind.PIPELINE):
                pass

        yield sse_event(
            SSEEventType.TEXT, refusal_reply, conversation_id=conv_id, exchange_id=exch_id
        )
