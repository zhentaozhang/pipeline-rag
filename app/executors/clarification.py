"""
歧义追问执行器
当 Orchestrator 检测到文档范围歧义时，生成追问文案引导用户选择。
"""

from collections.abc import AsyncIterator

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event
from app.executors.base import ConversationExecutor


class ClarificationExecutor(ConversationExecutor):
    """当 Orchestrator 检测到歧义时，生成追问问题引导用户补充信息"""

    mode = ExecutionMode.CLARIFICATION

    def __init__(self, task: ChatTaskInfo) -> None:
        self.task = task

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        from app.observability import SpanKind

        tracer = self.task.tracer
        conv_id = self.task.conversation_id
        exch_id = self.task.exchange_id

        clarification_reply = (
            "当前我无法稳定判断你想问哪份知识文档，请补充更具体的文档名、主题或关键词。"
            if plan is None
            else (
                plan.clarification_reply
                or "当前我无法稳定判断你想问哪份知识文档，请补充更具体的文档名、主题或关键词。"
            )
        )
        clarification_reason = "" if plan is None else (plan.clarification_reason or "")

        if self.task.debug_trace is not None and clarification_reason:
            self.task.debug_trace.retrieval_notes.append(clarification_reason)

        yield sse_event(
            SSEEventType.THINKING,
            "当前问题涉及多份候选文档，先向你确认知识范围。",
            conversation_id=conv_id,
            exchange_id=exch_id,
        )
        self.task.thinking_steps.append("当前问题涉及多份候选文档，先向你确认知识范围。")
        if clarification_reason:
            yield sse_event(
                SSEEventType.STATUS,
                clarification_reason,
                conversation_id=conv_id,
                exchange_id=exch_id,
            )

        if tracer is not None:
            async with tracer.span("clarification", kind=SpanKind.PIPELINE):
                pass

        yield sse_event(
            SSEEventType.TEXT, clarification_reply, conversation_id=conv_id, exchange_id=exch_id
        )
