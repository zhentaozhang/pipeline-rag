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
    # Task 1：chunk 级标注（按 ID 精确判定召回）。为空时由 ground_gold_chunks 由片段对齐得到。
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    relevant_parent_ids: list[str] = Field(default_factory=list)
    # Task 2：False = 检索/作答指标不适用（正确答案是"说明无依据"，不是召回到某条款）。
    answerable: bool = True
    # Task 2：True = 该题的正确答案是**不得编造**（无依据时必须明说，而不是给出具体数字）。
    expected_refusal: bool = False
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
    # 与 settings.rag.final_top_k 对齐：final_top_k=8 时不再报 R@10（可用结果<10 会让指标结构性失真）
    recall_at_final_k: float | None = None
    mrr: float | None = None  # 排序质量：首个命中的排名倒数
    ndcg_at_5: float | None = None  # 排序质量：nDCG@5
    ndcg_at_final_k: float | None = None  # 排序质量：nDCG@final_top_k
    # Task 1：按证据 ID 判定的指标（None = 该题无 gold，不计入均值）
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    retrieved_parent_ids: list[str] = Field(default_factory=list)
    recall_at_5_ids: float | None = None
    recall_at_final_k_ids: float | None = None
    mrr_ids: float | None = None
    ndcg_at_5_ids: float | None = None
    recall_at_5_parent_ids: float | None = None
    recall_at_final_k_parent_ids: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None

    # Task 2：拒答表现（只对 expected_refusal 的题有意义）
    answerable: bool = True
    expected_refusal: bool = False
    refused: bool | None = None
    unanswerable_reason: str = ""

    # 归因分析 (Retrieval Lab 方法论)
    stage_attribution: dict[str, Any] = Field(default_factory=dict)

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
