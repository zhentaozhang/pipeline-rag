from decimal import Decimal

import pytest

from app.orchestrator.fallback_router import FallbackRouter
from app.orchestrator.models import DocumentRouteCandidate, KnowledgeRouteDecision


def make_doc(document_id="1", name="部署手册", task_id="t1", score="0.9", category="cat", tags="tag"):
    return DocumentRouteCandidate(
        document_id=document_id,
        document_name=name,
        last_index_task_id=task_id,
        scope_code="A",
        scope_name="域A",
        business_category=category,
        document_tags=tags,
        score=Decimal(score),
        reason="r",
    )


class TestExtractKeywordsFromDocName:
    def test_cjk_characters(self):
        out = FallbackRouter.extract_keywords_from_doc_name("数据库安装指南.pdf")
        assert set(out) == {"数", "据", "库", "安", "装", "指", "南"}

    def test_english_tokens(self):
        out = FallbackRouter.extract_keywords_from_doc_name("Redis 配置手册.md")
        assert "redis" in out

    def test_strips_extensions(self):
        out = FallbackRouter.extract_keywords_from_doc_name("手册.pdf")
        assert "pdf" not in out

    def test_separators(self):
        out = FallbackRouter.extract_keywords_from_doc_name("A/B 配置-安装")
        assert "配" in out and "置" in out and "安" in out


class TestExtractFallbackTerms:
    def test_segments(self):
        terms = FallbackRouter.extract_fallback_terms("如何配置数据库", "配置数据库的方法")
        assert "配置数据库" in terms

    def test_short_terms_dropped(self):
        terms = FallbackRouter.extract_fallback_terms("a b c", "")
        assert terms == []

    def test_gram_generation(self):
        terms = FallbackRouter.extract_fallback_terms("数据库配置", "")
        joined = " ".join(terms)
        assert "数据" in joined and "库配" in joined
        assert len(terms) <= 40


class TestNormalizeFallbackText:
    def test_strips(self):
        assert FallbackRouter.normalize_fallback_text(" 部署 手册，安装。 ") == "部署手册安装"
        assert FallbackRouter.normalize_fallback_text("ABC") == "abc"


class TestFallbackDescriptorScore:
    def test_long_term_higher(self):
        d = make_doc(name="数据库安装配置手册")
        assert FallbackRouter.fallback_descriptor_score(d, ["数据库安装配置手册"]) == 12.0

    def test_medium_term(self):
        d = make_doc(name="数据库配置")
        assert FallbackRouter.fallback_descriptor_score(d, ["数据库配置"]) == 8.0

    def test_no_match_zero(self):
        d = make_doc(name="完全无关")
        assert FallbackRouter.fallback_descriptor_score(d, ["数据库"]) == 0.0

    def test_empty_content_or_terms(self):
        assert FallbackRouter.fallback_descriptor_score(make_doc(name=""), ["a"]) == 0.0
        assert FallbackRouter.fallback_descriptor_score(make_doc(name="x"), []) == 0.0

    def test_matches_category_and_tags(self):
        d = make_doc(name="手册", category="数据库", tags="部署")
        assert FallbackRouter.fallback_descriptor_score(d, ["数据库"]) == 4.0
        assert FallbackRouter.fallback_descriptor_score(d, ["部署"]) == 2.0


class TestMergeCandidates:
    def test_primary_priority_dedup(self):
        primary = [make_doc("1"), make_doc("2")]
        secondary = [make_doc("2"), make_doc("3")]
        out = FallbackRouter.merge_candidates(primary, secondary, 5)
        assert [c.document_id for c in out] == ["1", "2", "3"]

    def test_limit(self):
        primary = [make_doc(str(i)) for i in range(3)]
        secondary = [make_doc(str(i)) for i in range(3, 6)]
        out = FallbackRouter.merge_candidates(primary, secondary, 4)
        assert len(out) == 4


class TestSelectAutoCandidates:
    @pytest.mark.asyncio
    async def test_empty_decision_uses_fallback(self, monkeypatch):
        async def fake_fallback(q, rq, limit):
            return [make_doc("9")]

        monkeypatch.setattr(FallbackRouter, "fallback_documents", staticmethod(fake_fallback))
        out = await FallbackRouter.select_auto_candidates(None, "q", "r")
        assert [c.document_id for c in out] == ["9"]

    @pytest.mark.asyncio
    async def test_high_confidence_returns_candidates(self, monkeypatch):
        decision = KnowledgeRouteDecision(
            confidence=Decimal("0.90"),
            documents=[make_doc("1"), make_doc("2"), make_doc("3"), make_doc("4")],
        )
        out = await FallbackRouter.select_auto_candidates(decision, "q", "r")
        assert [c.document_id for c in out] == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_missing_task_id_filtered(self, monkeypatch):
        decision = KnowledgeRouteDecision(
            confidence=Decimal("0.90"),
            documents=[make_doc("1", task_id="t"), make_doc("2", task_id="")],
        )
        out = await FallbackRouter.select_auto_candidates(decision, "q", "r")
        assert [c.document_id for c in out] == ["1"]

    @pytest.mark.asyncio
    async def test_low_confidence_merges_fallback(self, monkeypatch):
        decision = KnowledgeRouteDecision(
            confidence=Decimal("0.10"),
            documents=[make_doc("1")],
        )

        async def fake_fallback(q, rq, limit):
            return [make_doc("2")]

        monkeypatch.setattr(FallbackRouter, "fallback_documents", staticmethod(fake_fallback))
        out = await FallbackRouter.select_auto_candidates(decision, "q", "r")
        assert [c.document_id for c in out] == ["1", "2"]
