from __future__ import annotations

import decimal
import math
import re
from decimal import ROUND_HALF_UP

from app.common.text_utils import normalize_text
from app.orchestrator.models import (
    DocumentRouteCandidate,
    KnowledgeRouteDecision,
    ScopeRouteCandidate,
    TopicRouteCandidate,
)


def _join(*values: str | None) -> str:
    return " ".join([str(v).strip() for v in values if v and str(v).strip()])


def _normalize_code(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize_text(value))


class ScopeAccumulator:
    def __init__(self, scope_code: str, scope_name: str):
        self.scope_code = scope_code
        self.scope_name = scope_name
        self.max_score: float = 0.0
        self.reason: str = ""


class TopicAccumulator:
    def __init__(self, topic_name: str, scope_code: str):
        self.topic_name = topic_name
        self.scope_code = scope_code
        self.max_score: float = 0.0
        self.reason: str = ""


class DocumentRouteMaterial:
    def __init__(self, document_id: int, route_text: str):
        self.document_id = document_id
        self.route_text = route_text


class RouteScorer:
    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        norm_l = sum(val * val for val in left)
        norm_r = sum(val * val for val in right)
        if norm_l <= 0 or norm_r <= 0:
            return 0.0
        return dot / (math.sqrt(norm_l) * math.sqrt(norm_r))

    def semantic_main_score(self, semantic_score: float) -> float:
        if semantic_score <= 0.20:
            return 0.0
        return (semantic_score - 0.20) * 50.0

    def lexical_assist(self, lexical_score: float | None) -> float:
        if lexical_score is None or lexical_score <= 0:
            return 0.0
        return min(10.0, lexical_score * 1.6)

    def keyword_entity_assist(self, query_terms: list[str], route_text: str) -> float:
        if not query_terms:
            return 0.0
        score = 0.0
        norm_content = normalize_text(route_text)
        for term in query_terms:
            if not self._looks_like_entity_term(term):
                continue
            norm_term = normalize_text(term)
            if not norm_term or len(norm_term) < 2:
                continue
            if norm_term in norm_content:
                score += 6.0
        return score

    def lexical_score(self, query_terms: list[str], content: str) -> float:
        normalized_content = normalize_text(content)
        if not normalized_content or not query_terms:
            return 0.0
        terms = sorted(
            set(normalize_text(t) for t in query_terms if len(t) >= 2),
            key=len,
            reverse=True,
        )
        score = 0.0
        matched: list[str] = []
        for term in terms:
            if any(term in existing for existing in matched):
                continue
            if term in normalized_content:
                matched.append(term)
                score += self._lexical_weight(len(term))
        return score

    @staticmethod
    def _lexical_weight(term_length: int) -> float:
        if term_length >= 8:
            return 12.0
        if term_length >= 5:
            return 8.0
        if term_length >= 3:
            return 4.0
        return 2.0

    def _looks_like_entity_term(self, term: str) -> bool:
        if not term or not term.strip():
            return False
        t = term.strip()
        return bool(re.search(r"[A-Za-z]", t)) or bool(re.search(r"\d", t)) or len(t) <= 4

    def to_decimal(self, score: float) -> decimal.Decimal:
        return decimal.Decimal(str(round(score, 4))).quantize(
            decimal.Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    def build_reason(self, query_terms: list[str], content: str, semantic_score: float) -> str:
        norm_content = normalize_text(content)
        matched: list[str] = []
        for t in query_terms:
            if normalize_text(t) in norm_content:
                matched.append(t)
                if len(matched) >= 3:
                    break

        if matched:
            return "命中关键词：" + "、".join(matched)
        if semantic_score >= 0.55:
            return "语义相似度高，基于文档画像与元数据召回"
        if semantic_score >= 0.35:
            return "语义相近，采用保守扩范围召回"
        return "基于文档画像与元数据综合召回"

    def resolve_confidence(self, documents: list[DocumentRouteCandidate]) -> decimal.Decimal:
        if not documents:
            return decimal.Decimal("0.0")
        top = float(documents[0].score)
        second = float(documents[1].score) if len(documents) > 1 else 0.0
        normalized = top / max(10.0, top + second + 5.0)
        return self.to_decimal(normalized)

    def resolve_decision_reason(
        self, documents: list[DocumentRouteCandidate], confidence: decimal.Decimal
    ) -> str:
        if not documents:
            return "没有找到可用候选文档"
        top_reason = documents[0].reason or ""
        if confidence is not None and confidence < decimal.Decimal("0.55"):
            return top_reason or "低置信度，已进入保守扩范围候选"
        return top_reason

    def tokenize(self, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []
        terms: set[str] = set()
        segments = re.split(r"[\s、，,；;：:（）()\-的和及与或]+", normalized)
        for seg in segments:
            trimmed = seg.strip()
            if len(trimmed) >= 2:
                terms.add(trimmed)
                self._expand_chinese_ngrams(terms, trimmed)
        return list(terms)[:40]

    def _expand_chinese_ngrams(self, terms: set[str], segment: str):
        normalized = segment.strip()
        if len(normalized) < 4:
            return
        max_gram = min(6, len(normalized))
        for g_len in range(2, max_gram + 1):
            for i in range(len(normalized) - g_len + 1):
                gram = normalized[i : i + g_len]
                if len(gram) >= 2:
                    terms.add(gram)

    def build_decision(
        self,
        scopes: list[ScopeRouteCandidate],
        topics: list[TopicRouteCandidate],
        documents: list[DocumentRouteCandidate],
    ) -> KnowledgeRouteDecision:
        decision = KnowledgeRouteDecision()
        decision.scopes = scopes
        decision.topics = topics
        decision.documents = documents
        confidence = self.resolve_confidence(documents)
        decision.confidence = confidence
        if not documents:
            decision.route_status = "FAILED"
        elif confidence < decimal.Decimal("0.55"):
            decision.route_status = "LOW_CONFIDENCE"
        else:
            decision.route_status = "SUCCESS"
        decision.reason = (
            "没有找到可用候选文档"
            if not documents
            else self.resolve_decision_reason(documents, confidence)
        )
        return decision
