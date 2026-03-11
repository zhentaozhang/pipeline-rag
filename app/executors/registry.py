"""
执行器注册表 — 按 ExecutionMode 分发到对应执行器

注册方式：通过 executor 类的 mode 属性自动发现并建立 mode→executor_class 映射。
"""

from collections.abc import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.executors.base import ConversationExecutor

logger = structlog.get_logger(__name__)


def _build_default_registry() -> dict[ExecutionMode, type[ConversationExecutor]]:
    from app.executors.agent import ReactAgentExecutor
    from app.executors.clarification import ClarificationExecutor
    from app.executors.graph import GraphExecutor, GraphThenEvidenceExecutor
    from app.executors.rag import RagChatExecutor
    from app.executors.refusal import RefusalExecutor

    reg: dict[ExecutionMode, type[ConversationExecutor]] = {}
    for cls in [
        ClarificationExecutor,
        RagChatExecutor,
        ReactAgentExecutor,
        GraphExecutor,
        GraphThenEvidenceExecutor,
        RefusalExecutor,
    ]:
        reg[cls.mode] = cls
    return reg


class ExecutorRegistry:
    """
    执行器路由注册中心。
    通过 ExecutionMode 查找并实例化对应的 executor，未注册的 mode 抛出 RuntimeError。
    """

    def __init__(self, db: AsyncSession, task: ChatTaskInfo) -> None:
        self.db = db
        self.task = task
        self._registry = _build_default_registry()

    def get(self, mode: ExecutionMode) -> ConversationExecutor:
        """根据执行模式查找并实例化对应的执行器。"""
        from app.executors.clarification import ClarificationExecutor
        from app.executors.refusal import RefusalExecutor

        cls = self._registry.get(mode)
        if cls is None:
            raise RuntimeError(f"未找到执行模式对应的执行器: {mode}")
        if cls in (ClarificationExecutor, RefusalExecutor):
            return cls(self.task)
        return cls(self.db, self.task)

    async def dispatch(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        """根据执行计划选择执行器，产生 SSE 事件流"""
        logger.info(
            "dispatching",
            mode=plan.mode,
            supervisor_mode=plan.supervisor_mode,
            conversation_id=self.task.conversation_id,
        )

        if plan.supervisor_mode or plan.mode == ExecutionMode.MULTI_AGENT:
            from app.executors.parallel_executor import ParallelExecutor

            executor = ParallelExecutor(self.db, self.task, self)
            async for chunk in executor.execute(plan):
                yield chunk
            return

        executor = self.get(plan.mode)
        async for chunk in executor.execute(plan):
            yield chunk
