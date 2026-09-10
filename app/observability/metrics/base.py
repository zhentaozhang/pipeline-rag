from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

_MARKDOWN_FENCE = re.compile(r"^```(?:json)?\s*|```$")


def parse_json_safe(text: str, default: Any = None) -> dict[str, Any] | list[Any] | None:
    """Parse JSON from LLM output, stripping markdown fences if present.

    Handles:
      - raw JSON: {"key": "value"}
      - markdown-wrapped: ```json\n{"key": "value"}\n```
      - extra text before/after: Sure! Here is the data: {"key": "value"}
    """
    if default is None:
        default = {}
    text = _MARKDOWN_FENCE.sub("", text).strip()
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")

    candidates: list[tuple[int, int]] = []
    if brace_start != -1 and brace_end > brace_start:
        candidates.append((brace_start, brace_end + 1))
    if bracket_start != -1 and bracket_end > bracket_start:
        candidates.append((bracket_start, bracket_end + 1))

    for start, end in candidates:
        candidate = text[start:end]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            continue
        return default


class MetricResult(BaseModel):
    metric_name: str
    value: float
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.metric_name}={self.value:.4f}"


@dataclass
class Metric(ABC):
    name: str = ""
    eval_llm: Any = None
    model: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.__class__.__name__.lower()

    async def _call_llm(
        self,
        *,
        tracer: Any,
        name: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """调用评估 LLM 并把该次调用记录为 Langfuse generation（tracer 未启用时静默短路）。"""
        resp = await self.eval_llm.chat.completions.create(
            model=self.model, messages=messages, **kwargs
        )
        content = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        from app.observability.llm_observe import record_generation

        record_generation(
            tracer,
            name,
            model=self.model,
            input=messages,
            output=content,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
        return content

    @abstractmethod
    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
        tracer: Any = None,
    ) -> MetricResult: ...
