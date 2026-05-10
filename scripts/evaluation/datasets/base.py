from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvalQuestion(BaseModel):
    """一条测试数据：问题 + 标准答案 + 应检出的上下文"""

    id: str
    question: str
    ground_truth_answer: str
    relevant_contexts: list[str] = Field(default_factory=list)
    relevant_document_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    """单条测试的评估结果"""

    question_id: str
    question: str
    ground_truth_answer: str = ""

    # 流水线产出
    generated_answer: str = ""
    retrieved_contexts: list[str] = Field(default_factory=list)
    rewritten_question: str = ""
    generated_recommendations: list[str] = Field(default_factory=list)

    # 5 个评估指标
    faithfulness_score: float | None = None
    answer_relevancy_score: float | None = None
    context_precision_score: float | None = None
    answer_correctness_score: float | None = None
    context_recall_score: float | None = None

    # 性能
    retrieval_ms: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None

    # 状态
    status: str = "pending"
    error: str = ""


class EvalRunReport(BaseModel):
    """一次评估运行的汇总报告"""

    run_id: str = ""
    timestamp: str = ""
    total_questions: int = 0
    passed: int = 0
    failed: int = 0
    results: list[EvalResult] = Field(default_factory=list)

    # 平均分
    avg_faithfulness: float | None = None
    avg_answer_relevancy: float | None = None
    avg_context_precision: float | None = None
    avg_answer_correctness: float | None = None
    avg_context_recall: float | None = None
