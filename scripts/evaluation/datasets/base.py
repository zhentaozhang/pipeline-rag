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


class DecisionSample(BaseModel):
    """一条"判断型"任务标注样本（用于 JEV vs 旧方案的 P/R/F1 A-B 对比）

    - input：待判定的主文本（问题 / 用户提问）
    - label：正样本真值（True = 正类，如"相关"/"不安全"）
    - context：可选的第二文本（如检索片段），用于 context_relevance 类任务
    """

    id: str
    input: str
    label: bool
    context: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChoiceSample(BaseModel):
    """一条多分类（Choice）标注样本（label 为类别名）"""

    id: str
    input: str
    label: str
    context: str | None = None
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
    recall_at_5: float | None = None  # 量化能力 #2
    recall_at_10: float | None = None
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
