"""质量审核改用 yes/no 判据（而不是 1–10 分档）：

公开参考实现（feder-cr/jev）明确把"让模型吐一个 1-10 分"列为反模式：
分数是生成文本、要解析、会聚簇，而且一个数字把多个判据混在一起，
失败时说不清是哪一条没过。这里换成 4 个 noul 取平均，可解释、可标定。
"""

from __future__ import annotations

import pytest

from app.executors.rag import QUALITY_CRITERIA, quality_from_answers


def _answers(**kw):
    return {name: {"noul": kw[name]} for name in QUALITY_CRITERIA if name in kw}


def test_criteria_are_yes_no_questions():
    assert set(QUALITY_CRITERIA) == {"on_topic", "specific", "complete", "consistent"}
    for text in QUALITY_CRITERIA.values():
        assert text.endswith("）") or "是否" in text, "每个判据都必须是一个可用 yes/no 回答的句子"


def test_mean_of_probabilities():
    mean, probs = quality_from_answers(
        _answers(on_topic=0.9, specific=0.8, complete=0.7, consistent=0.6)
    )
    assert probs == {"on_topic": 0.9, "specific": 0.8, "complete": 0.7, "consistent": 0.6}
    assert mean == pytest.approx(0.75)


def test_missing_criterion_raises_instead_of_guessing():
    with pytest.raises(ValueError, match="complete"):
        quality_from_answers(_answers(on_topic=0.9, specific=0.8, consistent=0.6))


@pytest.mark.asyncio
async def test_score_is_reported_on_the_same_zero_to_ten_scale(monkeypatch):
    """调用方与 SSE 都按 0-10 分工作，换判据不能改外部口径。"""
    import app.infra.jev_client as jc
    from app.executors.rag import AnswerQualityChecker

    async def _fake_decide(flag, state, questions, parse, **kw):
        assert set(questions) == set(QUALITY_CRITERIA)
        assert all(q["type"] == "noul" for q in questions.values())
        return parse(_answers(on_topic=0.9, specific=0.9, complete=0.8, consistent=0.8))

    monkeypatch.setattr(jc, "jev_decide", _fake_decide)
    checker = AnswerQualityChecker()
    assert await checker._jev_quality_score("q", "a") == pytest.approx(8.5)


@pytest.mark.asyncio
async def test_disabled_flag_returns_none(monkeypatch):
    import app.infra.jev_client as jc
    from app.executors.rag import AnswerQualityChecker

    async def _none(flag, state, questions, parse, **kw):
        return None

    monkeypatch.setattr(jc, "jev_decide", _none)
    assert await AnswerQualityChecker()._jev_quality_score("q", "a") is None
