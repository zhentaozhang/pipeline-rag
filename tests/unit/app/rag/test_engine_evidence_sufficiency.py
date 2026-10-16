"""证据充分性判定（JEV Noul）单测。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chat.schema import Evidence, SubQuestion, SubQuestionEvidence
from app.rag.engine import RagRetrievalContext, RagRetrievalEngine


def _engine() -> RagRetrievalEngine:
    return RagRetrievalEngine.__new__(RagRetrievalEngine)


def _ctx(contents: list[str]) -> RagRetrievalContext:
    evs = [
        Evidence(content=c, reference_id=str(i + 1), chunk_id=f"c{i}", doc_id="d", title="t")
        for i, c in enumerate(contents)
    ]
    sq = SubQuestion(index=0, text="q", original="q")
    return RagRetrievalContext(
        retrieval_question="q",
        sub_question_evidence_list=[SubQuestionEvidence(sub_question=sq, evidences=evs)],
    )


def _patch_jev(answers):
    mock = MagicMock()
    mock.system_one = AsyncMock(return_value=answers)
    return patch("app.infra.jev_client.get_jev_client", return_value=mock)


def _enable(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().jev, "evidence_sufficiency_enabled", True)


@pytest.mark.asyncio
async def test_empty_context_is_insufficient():
    assert await _engine()._evidence_is_sufficient("q", _ctx([])) is False


@pytest.mark.asyncio
async def test_jev_says_sufficient(monkeypatch):
    _enable(monkeypatch)
    with _patch_jev({"sufficient": {"noul": 0.9}}):
        assert await _engine()._evidence_is_sufficient("q", _ctx(["证据A"])) is True


@pytest.mark.asyncio
async def test_jev_says_insufficient(monkeypatch):
    _enable(monkeypatch)
    with _patch_jev({"sufficient": {"noul": 0.1}}):
        assert await _engine()._evidence_is_sufficient("q", _ctx(["证据A"])) is False


@pytest.mark.asyncio
async def test_jev_error_defaults_to_sufficient(monkeypatch):
    _enable(monkeypatch)
    mock = MagicMock()
    mock.system_one = AsyncMock(side_effect=RuntimeError("down"))
    with patch("app.infra.jev_client.get_jev_client", return_value=mock):
        # 异常时按"充分"处理，避免无限纠错
        assert await _engine()._evidence_is_sufficient("q", _ctx(["证据A"])) is True


@pytest.mark.asyncio
async def test_jev_disabled_preserves_original_behaviour(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().jev, "evidence_sufficiency_enabled", False)
    # 非空 → 充分（原行为）
    assert await _engine()._evidence_is_sufficient("q", _ctx(["证据A"])) is True
