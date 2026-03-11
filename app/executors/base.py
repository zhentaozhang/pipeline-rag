"""
统一对话执行器抽象基类
所有执行器必须实现 execute() 方法，返回 SSE 事件流。
"""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.chat.schema import ExecutionPlan, WorkerResult
from app.common.enums import ExecutionMode
from app.common.sse import sse_event


class ConversationExecutor(ABC):
    """所有执行器必须实现的标准接口"""

    mode: ExecutionMode

    def _emit(self, event_type: str, content: Any = None) -> str:
        task = getattr(self, "task", None)
        conv_id = getattr(task, "conversation_id", None) if task else None
        exch_id = getattr(task, "exchange_id", None) if task else None
        return sse_event(event_type, content, conversation_id=conv_id, exchange_id=exch_id)

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        """执行对话任务，返回 SSE 事件流"""

    async def execute_structured(self, plan: ExecutionPlan) -> WorkerResult:
        """执行任务并以结构化 WorkerResult 返回（默认实现：从 SSE 流提取 text）"""
        text_parts: list[str] = []

        async for chunk in self.execute(plan):
            try:
                prefix = "data: "
                if not chunk.startswith(prefix):
                    continue
                data = json.loads(chunk[len(prefix) :].strip())
                event_type = data.get("type")
                if event_type in ("text", "message"):
                    content = data.get("content", "")
                    if isinstance(content, str):
                        text_parts.append(content)
            except json.JSONDecodeError:
                continue

        refs: list[dict] = []
        task = getattr(self, "task", None)
        if task is not None:
            refs = list(getattr(task, "references", []))

        return WorkerResult(
            sub_plan_id="", mode=self.mode, text="".join(text_parts), references=refs
        )
