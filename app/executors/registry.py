"""
执行器注册表 — 按 ExecutionMode 分发到对应执行器

注册方式：通过 executor 类的 mode 属性自动发现并建立 mode→executor_class 映射。
"""

from collections.abc import AsyncIterator, Callable
from typing import cast

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

    # 显式标注元素类型：否则 mypy 会把 cls 推断为异质类对象的 join（ABCMeta），
    # 导致 cls.mode 与赋值均报错。
    executors: list[type[ConversationExecutor]] = [
        ClarificationExecutor,
        RagChatExecutor,
        ReactAgentExecutor,
        GraphExecutor,
        GraphThenEvidenceExecutor,
        RefusalExecutor,
    ]
    return {cls.mode: cls for cls in executors}


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
        if mode == ExecutionMode.MULTI_AGENT:
            from app.executors.parallel_executor import ParallelExecutor

            return ParallelExecutor(self.db, self.task, self)

        # RAG_CHAT 别名回退到 RETRIEVAL（RagChatExecutor）
        if mode == ExecutionMode.RAG_CHAT:
            mode = ExecutionMode.RETRIEVAL

        from app.executors.clarification import ClarificationExecutor
        from app.executors.refusal import RefusalExecutor

        cls = self._registry.get(mode)
        if cls is None:
            raise RuntimeError(f"未找到执行模式对应的执行器: {mode}")
        # 两类执行器不依赖 DB，构造签名与其余执行器不同；
        # 用 Callable[..., ConversationExecutor] 收敛异构构造调用（Protocol 仅声明
        # __init__ 时不是可调用类型，故不能用 Protocol）。
        ctor = cast("Callable[..., ConversationExecutor]", cls)
        if issubclass(cls, (ClarificationExecutor, RefusalExecutor)):
            return ctor(self.task)
        return ctor(self.db, self.task)

    async def dispatch(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        """根据执行计划选择执行器，产生 SSE 事件流"""
        logger.info(
            "dispatching",
            mode=plan.mode,
            supervisor_mode=plan.supervisor_mode,
            conversation_id=self.task.conversation_id,
        )

        if plan.supervisor_mode or plan.mode == ExecutionMode.MULTI_AGENT:
            executor: ConversationExecutor = self.get(ExecutionMode.MULTI_AGENT)
            async for chunk in executor.execute(plan):
                yield chunk
            return

        executor = self.get(plan.mode)
        async for chunk in executor.execute(plan):
            yield chunk
