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
            return json.loads(candidate)
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

    @abstractmethod
    async def ascore(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> MetricResult:
        ...



