"""Langfuse trace 适配层：把稳定的 Tracer API 映射到 langfuse 4.x observation 模型

langfuse 4.x 移除了旧的 trace()/span() API，改为 start_observation() +
propagate_attributes()。本模块封装这些底层调用，对外暴露与自研 Tracer
生命周期一致的 start_root/start_span/end_span/add_score/flush，便于在
Tracer 中按 feature flag 无缝切换。
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from langfuse import Langfuse

# langfuse 4.x observation 类型（start_observation 的重载按此区分）
AsType = Literal[
    "span",
    "generation",
    "embedding",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
]

# 自研 SpanKind -> langfuse as_type 映射
KIND_TO_AS_TYPE: dict[str, AsType] = {
    "llm": "generation",
    "agent": "agent",
    "tool": "tool",
    "evaluation": "evaluator",
    "retrieval": "retriever",
    "pipeline": "span",
    "channel": "span",
    "memory": "span",
    "rewrite": "span",
    "classify": "span",
    "route": "span",
    "recommend": "span",
}


def _clip(value: Any) -> Any:
    """按 ``LANGFUSE_MAX_IO_CHARS`` 截断 input/output，避免全量明文上报。"""
    if value is None:
        return None
    from app.config import get_settings

    max_chars = get_settings().langfuse.max_io_chars
    if max_chars <= 0:
        return value
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "…[truncated]"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) <= max_chars:
        return value
    return text[:max_chars] + "…[truncated]"


class LangfuseTraceExporter:
    """一次 exchange 对应的 langfuse trace 上报器"""

    def __init__(
        self,
        client: Langfuse,
        trace_id: str,
        conversation_id: str,
        exchange_id: int,
        session_id: str | None = None,
    ) -> None:
        self._client = client
        self._trace_id = trace_id
        self.conversation_id = conversation_id
        self.exchange_id = exchange_id
        self.session_id = session_id

    @staticmethod
    def _as_type(kind: str) -> AsType:
        return KIND_TO_AS_TYPE.get(kind, "span")

    def start_root(self, name: str, *, input: Any = None, kind: str = "pipeline"):
        # as_type 为动态值，无法静态匹配 langfuse 的按类型重载：cast 到 Any 绕过
        return self._client.start_observation(
            trace_context={"trace_id": self._trace_id},
            name=name,
            as_type=cast(Any, self._as_type(kind)),
            input=_clip(input),
            metadata={
                "conversation_id": self.conversation_id,
                "exchange_id": self.exchange_id,
                "session_id": self.session_id,
            },
        )

    def start_span(self, parent, name: str, *, input: Any = None, kind: str = "pipeline"):
        return parent.start_observation(
            name=name,
            as_type=self._as_type(kind),
            input=_clip(input),
        )

    def end_span(
        self,
        obs,
        *,
        output: Any = None,
        level: str | None = None,
    ) -> None:
        """结束 span：output/level 需在 end() 前通过 update() 写入（langfuse 4.x end 仅收 end_time）"""
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = _clip(output)
        if level is not None:
            update_kwargs["level"] = level
        if update_kwargs:
            obs.update(**update_kwargs)
        obs.end()

    def add_score(self, obs, name: str, value: float, *, reason: str | None = None) -> None:
        obs.score(name=name, value=value, comment=reason)

    def record_generation(
        self,
        parent,
        name: str,
        *,
        model: str,
        input: Any = None,
        output: Any = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
        level: str | None = None,
    ) -> None:
        """记录一次完整的 LLM generation：start(model) -> update(usage/cost/output) -> end"""
        gen = parent.start_observation(
            name=name,
            as_type="generation",
            input=_clip(input),
            model=model,
        )
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = _clip(output)
        if usage_details:
            update_kwargs["usage_details"] = usage_details
        if cost_details:
            update_kwargs["cost_details"] = cost_details
        if level is not None:
            update_kwargs["level"] = level
        if update_kwargs:
            gen.update(**update_kwargs)
        gen.end()

    def flush(self) -> None:
        self._client.flush()
