"""P0-2：评测必须复刻生产执行器的引用校验与质量审核，否则 V3(JEV) 与 V2 在评测里等价。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.evaluation.postprocess import (
    citation_accuracy,
    references_from_evidence,
    run_postprocess,
)


class TestCitationAccuracy:
    def test_no_citations_returns_none(self):
        assert citation_accuracy("没有引用的回答", []) is None

    def test_all_supported(self):
        assert citation_accuracy("答案[1]和[2]", []) == 1.0

    def test_half_unsupported(self):
        assert citation_accuracy("答案[1]和[2]", [2]) == 0.5

    def test_bad_ref_not_cited_ignored(self):
        assert citation_accuracy("答案[1]", [5]) == 1.0

    def test_duplicate_citations_counted_once(self):
        assert citation_accuracy("[1][1][1]", [1]) == 0.0


@pytest.mark.asyncio
async def test_run_postprocess_records_verified_answer_and_latency():
    async def fake_verify(**kwargs):
        return ("答案[1]\n\n（注：引用[2]未能核实）", [2], {"checked": [1, 2]})

    with patch("app.chat.citation_verifier.verify_citations", fake_verify):
        result = await run_postprocess(
            question="q",
            answer="答案[1][2]",
            references=[{"id": 1}],
            fallback=None,
            run_quality=False,
        )
    assert result.bad_refs == [2]
    assert "未能核实" in result.answer
    assert result.citation_meta == {"checked": [1, 2]}
    assert result.citation_ms >= 0
    assert result.quality_passed is None


@pytest.mark.asyncio
async def test_run_postprocess_swallows_verify_errors():
    async def boom(**kwargs):
        raise RuntimeError("jev down")

    with patch("app.chat.citation_verifier.verify_citations", boom):
        result = await run_postprocess(
            question="q", answer="答案[1]", references=[], fallback=None, run_quality=False
        )
    assert result.answer == "答案[1]"
    assert "jev down" in result.citation_meta["error"]


@pytest.mark.asyncio
async def test_run_postprocess_quality_result():
    class _Q:
        passed = False
        score = 3.5
        feedback = "缺少依据"

    class _Checker:
        async def check(self, question, answer, reference_titles=None):
            return _Q()

    async def fake_verify(**kwargs):
        return (kwargs["answer"], [], {})

    with (
        patch("app.chat.citation_verifier.verify_citations", fake_verify),
        patch("app.executors.rag.AnswerQualityChecker", _Checker),
    ):
        result = await run_postprocess(
            question="q", answer="答案[1]", references=[], fallback=None, run_quality=True
        )
    assert result.quality_passed is False
    assert result.quality_score == 3.5
    assert result.quality_feedback == "缺少依据"


class TestReferencesFromEvidence:
    def test_maps_evidence_to_reference_dict(self):
        from types import SimpleNamespace

        evs = [
            SimpleNamespace(
                reference_id=1,
                title="员工手册 › 第5条",
                section_title="第5条 试用期规定",
                document_name="员工手册.md",
                content="x" * 50,
                source_type="document",
                url="",
                document_id="d1",
                chunk_id="c1",
                parent_block_id="p1",
            )
        ]
        refs = references_from_evidence(evs)
        assert refs[0]["id"] == 1
        assert refs[0]["section_title"] == "第5条 试用期规定"
        assert refs[0]["content"].startswith("x")
        assert refs[0]["parent_block_id"] == "p1"

    def test_skips_empty_content_and_keeps_reference_id(self):
        from types import SimpleNamespace

        evs = [
            SimpleNamespace(reference_id=7, content="", title="a"),
            SimpleNamespace(reference_id=8, content="hello [1]", title="b"),
        ]
        refs = references_from_evidence(evs)
        assert len(refs) == 1
        assert refs[0]["id"] == 8, "保留 reference_id，与 Prompt 里渲染的 [n] 编号一致"


@pytest.mark.asyncio
async def test_run_postprocess_records_quality_status():
    class _Checker:
        async def check(self, question, answer):
            return type(
                "Q",
                (),
                {"passed": True, "score": 10.0, "feedback": "", "status": "unknown"},
            )()

    with patch("app.executors.rag.AnswerQualityChecker", _Checker):
        result = await run_postprocess(
            question="q",
            answer="答案",
            references=[{"id": 1}],
            fallback=None,
            run_quality=True,
        )
    assert result.quality_passed is True
    assert result.quality_status == "unknown"
