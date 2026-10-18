"""引用校验：缺分数不能被当成"高置信支持"，审计崩掉必须留未知标记。"""

from __future__ import annotations

import types

import pytest

import app.chat.citation_verifier as cv_module
from app.chat.citation_verifier import verify_citations


class _FakeJev:
    def __init__(self, answers):
        self._answers = answers

    async def system_one(self, state, questions):
        return self._answers


class _Fallback:
    def __init__(self, payload='{"unsupported": []}', error=None):
        self._payload = payload
        self._error = error
        self.calls = 0

    async def chat_completion(self, **kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        message = types.SimpleNamespace(content=self._payload)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=None)


def _settings(verify_enabled=True):
    jev = types.SimpleNamespace(
        citation_verify_enabled=verify_enabled,
        citation_confidence_threshold=0.60,
        citation_review_low=0.45,
    )
    return types.SimpleNamespace(jev=jev)


@pytest.mark.asyncio
async def test_missing_noul_escalates_instead_of_trusting(monkeypatch):
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: _FakeJev({}))
    fallback = _Fallback()

    answer, bad, meta = await verify_citations(fallback, "答案[1]", [{"content": "证据"}], "问题")
    assert fallback.calls == 1, "缺分数必须升级到 LLM 审计"
    assert meta["status"] == "judged"
    assert bad == []
    assert answer == "答案[1]"


@pytest.mark.asyncio
async def test_all_scores_present_stays_on_jev_path(monkeypatch):
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "app.infra.jev_client.get_jev_client",
        lambda: _FakeJev({"cite_1": {"noul": 0.9}}),
    )
    fallback = _Fallback()

    answer, bad, meta = await verify_citations(fallback, "答案[1]", [{"content": "证据"}], "问题")
    assert fallback.calls == 0
    assert meta["status"] == "jev_judged"
    assert bad == []


@pytest.mark.asyncio
async def test_llm_audit_error_marks_unknown_refs(monkeypatch):
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings(verify_enabled=False))
    fallback = _Fallback(error=RuntimeError("audit down"))

    answer, bad, meta = await verify_citations(fallback, "答案[1]", [{"content": "证据"}], "问题")
    assert meta["status"] == "error"
    assert meta["unknown_refs"] == [1]
    assert bad == []
    assert answer == "答案[1]"
