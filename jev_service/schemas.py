"""
JEV API 协议定义
对齐 TypeSafe AI Jev 协议规范
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QuestionItem(BaseModel):
    """单个决策问题描述"""

    type: Literal["noul", "choice", "score"] = Field(
        description="决策原语类型: noul(布尔判断), choice(枚举选择), score(等级评分)"
    )
    instructions: str = Field(default="", description="评判指令与标准")
    options: dict[str, str] | None = Field(
        default=None, description="choice 原语对应的候选选项 (key -> 描述)"
    )
    levels: list[str] | None = Field(default=None, description="score 原语对应的一组有序等级标签")


class SystemOneRequest(BaseModel):
    """System One 判断请求体"""

    model: str = Field(default="jev-local", description="判断模型标识")
    state: str = Field(description="待评估的非结构化上下文/应用状态")
    questions: dict[str, QuestionItem] = Field(description="问题集合 (name -> QuestionItem)")


class SystemOneResponse(BaseModel):
    """System One 判断响应体"""

    answers: dict[str, Any] = Field(description="各问题的结构化决策答案与置信度")
    latency_ms: float = Field(description="服务端推理执行耗时 (毫秒)")
    model: str = Field(default="jev-local", description="处理该请求的模型")
