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


@pytest.mark.asyncio
async def test_dangling_citation_is_rejected_without_any_llm_call(monkeypatch):
    """[7] 在只有 1 条证据时必然不成立：确定性判负，不该为此花一次模型调用。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    fallback = _Fallback()

    answer, bad, meta = await verify_citations(
        fallback, "试用期一个月[7]", [{"content": "试用期"}], "问题"
    )

    assert fallback.calls == 0
    assert meta["status"] == "deterministic_unsupported"
    assert bad == [7]
    assert "没有对应的证据" in answer


@pytest.mark.asyncio
async def test_fabricated_document_without_citation_is_caught(monkeypatch):
    """最伤的失败模式：没有 [n]，却编了一份语料里不存在的文档。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    fallback = _Fallback()

    answer, bad, meta = await verify_citations(
        fallback,
        "按《员工在职进修与专业资格考证补贴办法》第5.1条，A 类城市全额报销。",
        [{"content": "第5条 试用期规定", "document_name": "01_员工手册.md"}],
        "进修补贴怎么报",
    )

    assert fallback.calls == 0
    assert meta["status"] == "deterministic_unsupported"
    assert "员工在职进修与专业资格考证补贴办法" in answer
    assert bad == []


def test_needs_citation_check_covers_uncited_hallucination():
    from app.chat.answer_grounding import needs_citation_check

    refs = [{"content": "第5条 试用期规定", "document_name": "01_员工手册.md"}]
    assert needs_citation_check("答案[1]", refs) is True
    assert needs_citation_check("答案", refs) is False
    assert needs_citation_check("按《不存在的办法》执行", refs) is True


@pytest.mark.asyncio
async def test_uncited_quantitative_claim_is_reported_but_not_blocking(monkeypatch):
    """没引用编号的数值句：不阻断（可能是常识），但必须能在元信息里看到。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "app.infra.jev_client.get_jev_client", lambda: _FakeJev({"cite_1": {"noul": 0.9}})
    )
    fallback = _Fallback()

    answer, bad, meta = await verify_citations(
        fallback, "住宿上限 800 元/晚[1]，另有 300 元餐补。", [{"content": "800元/晚"}], "住宿标准"
    )

    assert meta["status"] == "jev_judged"
    assert meta["uncited_claims"] == ["另有 300 元餐补。"]
    assert bad == []
