"""RouteScorer 单元测试：余弦相似度、打分组合、置信度、决策构建（纯逻辑）。"""

import decimal

import pytest

from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision
from app.orchestrator.route_scorer import RouteScorer

scorer = RouteScorer()


def _doc(document_id: str, score: float, reason: str = "") -> DocumentRouteCandidate:
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name=f"doc-{document_id}",
        last_index_task_id="",
        scope_code="",
        scope_name="",
        business_category="",
        document_tags="",
        score=decimal.Decimal(str(score)),
        reason=reason,
    )


class TestCosineSimilarity:
    def test_empty_or_mismatched_returns_zero(self):
        assert RouteScorer.cosine_similarity([], [1.0]) == 0.0
        assert RouteScorer.cosine_similarity([1.0, 2.0], [1.0]) == 0.0
        assert RouteScorer.cosine_similarity([1.0], []) == 0.0

    def test_identical_vectors(self):
        assert RouteScorer.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert RouteScorer.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_partial_similarity(self):
        sim = RouteScorer.cosine_similarity([1.0, 1.0], [1.0, 0.0])
        assert 0 < sim < 1.0


class TestScoreFunctions:
    def test_semantic_main_score_below_threshold_zero(self):
        assert scorer.semantic_main_score(0.20) == 0.0
        assert scorer.semantic_main_score(0.10) == 0.0

    def test_semantic_main_score_scaling(self):
        assert scorer.semantic_main_score(0.5) == pytest.approx(15.0)

    def test_lexical_assist_none_or_negative_zero(self):
        assert scorer.lexical_assist(None) == 0.0
        assert scorer.lexical_assist(-1) == 0.0
        assert scorer.lexical_assist(0) == 0.0

    def test_lexical_assist_capped_at_10(self):
        assert scorer.lexical_assist(10.0) == 10.0
        assert scorer.lexical_assist(100.0) == 10.0
        assert scorer.lexical_assist(0.5) == pytest.approx(0.8)

    def test_lexical_weight_grading(self):
        assert RouteScorer._lexical_weight(2) == 2.0
        assert RouteScorer._lexical_weight(3) == 4.0
        assert RouteScorer._lexical_weight(5) == 8.0
        assert RouteScorer._lexical_weight(8) == 12.0

    def test_looks_like_entity_term(self):
        assert RouteScorer._looks_like_entity_term(scorer, "RAG") is True
        assert RouteScorer._looks_like_entity_term(scorer, "chunk") is True
        assert RouteScorer._looks_like_entity_term(scorer, "配置项") is True
        assert RouteScorer._looks_like_entity_term(scorer, "这是一个非常长的纯中文术语") is False
        assert RouteScorer._looks_like_entity_term(scorer, "  ") is False


class TestKeywordEntityAssist:
    def test_empty_terms_zero(self):
        assert scorer.keyword_entity_assist([], "内容") == 0.0

    def test_entity_term_hit_adds_6(self):
        score = scorer.keyword_entity_assist(["RAG"], "本文介绍 RAG 架构")
        assert score == 6.0

    def test_short_term_skipped_after_normalization(self):
        score = scorer.keyword_entity_assist(["a"], "包含 a 的内容")
        assert score == 0.0


class TestLexicalScore:
    def test_empty_inputs_zero(self):
        assert scorer.lexical_score([], "内容") == 0.0
        assert scorer.lexical_score(["词"], "  ") == 0.0

    def test_term_hit_weighed_by_length(self):
        score = scorer.lexical_score(["长词长词长词长词"], "本文包含长词长词长词长词")
        assert score == 12.0

    def test_longest_match_takes_priority(self):
        score = scorer.lexical_score(["chunk_size", "chunk"], "配置 chunk_size 参数")
        assert score == 12.0

    def test_multiple_terms_accumulate(self):
        score = scorer.lexical_score(["向量", "检索"], "向量检索系统")
        assert score == pytest.approx(2.0 + 2.0)


class TestToDecimal:
    def test_rounds_half_up_four_places(self):
        assert scorer.to_decimal(0.12345) == decimal.Decimal("0.1235")
        assert scorer.to_decimal(0.12344) == decimal.Decimal("0.1234")


class TestBuildReason:
    def test_keyword_hit_reason(self):
        reason = scorer.build_reason(["RAG", "多余词"], "本文讲 RAG 检索", 0.1)
        assert reason.startswith("命中关键词：")

    def test_high_semantic_reason(self):
        assert scorer.build_reason([], "内容", 0.6) == "语义相似度高，基于文档画像与元数据召回"

    def test_mid_semantic_reason(self):
        assert scorer.build_reason([], "内容", 0.4) == "语义相近，采用保守扩范围召回"

    def test_low_semantic_fallback_reason(self):
        assert scorer.build_reason([], "内容", 0.1) == "基于文档画像与元数据综合召回"


class TestResolveConfidence:
    def test_empty_documents_zero(self):
        assert scorer.resolve_confidence([]) == decimal.Decimal("0.0")

    def test_single_document(self):
        confidence = scorer.resolve_confidence([_doc("1", 0.9)])
        assert confidence == decimal.Decimal("0.9") / decimal.Decimal("10.0")

    def test_two_documents(self):
        confidence = scorer.resolve_confidence([_doc("1", 0.8), _doc("2", 0.2)])
        expected = decimal.Decimal("0.8") / decimal.Decimal("10.0")
        assert confidence == expected


class TestResolveDecisionReason:
    def test_no_documents(self):
        assert scorer.resolve_decision_reason([], decimal.Decimal("0.0")) == "没有找到可用候选文档"

    def test_low_confidence_uses_top_reason(self):
        reason = scorer.resolve_decision_reason(
            [_doc("1", 0.1, reason="低分理由")], decimal.Decimal("0.3")
        )
        assert reason == "低分理由"

    def test_high_confidence_uses_top_reason(self):
        reason = scorer.resolve_decision_reason(
            [_doc("1", 0.9, reason="高分理由")], decimal.Decimal("0.8")
        )
        assert reason == "高分理由"


class TestTokenize:
    def test_empty_returns_empty(self):
        assert scorer.tokenize("") == []
        assert scorer.tokenize("   ") == []

    def test_splits_on_separators(self):
        terms = scorer.tokenize("RAG 和 向量检索、Embedding")
        assert "RAG" in terms
        assert "向量检索" in terms
        assert "Embedding" in terms

    def test_expands_chinese_ngrams(self):
        terms = scorer.tokenize("向量检索")
        assert "向量检" in terms
        assert "量检索" in terms

    def test_short_segments_not_expanded(self):
        terms = scorer.tokenize("三步")
        assert len(terms) <= 1

    def test_max_40_terms(self):
        terms = scorer.tokenize("词" * 40 + "，" + "元" * 40)
        assert len(terms) <= 40


class TestBuildDecision:
    def test_no_documents_failed(self):
        decision = scorer.build_decision([], [], [])
        assert decision.route_status == "FAILED"
        assert decision.reason == "没有找到可用候选文档"
        assert decision.top_document() is None

    def test_low_confidence_status(self):
        decision = scorer.build_decision([], [], [_doc("1", 0.1)])
        assert decision.route_status == "LOW_CONFIDENCE"

    def test_success_status(self):
        decision = scorer.build_decision([], [], [_doc("1", 9.0), _doc("2", 1.0)])
        assert decision.route_status == "SUCCESS"
        assert decision.top_document().document_id == "1"

    def test_decision_is_route_object(self):
        decision = scorer.build_decision([], [], [_doc("1", 0.9)])
        assert isinstance(decision, KnowledgeRouteDecision)
