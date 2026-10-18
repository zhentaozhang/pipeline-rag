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


class _RecordingJev:
    """记录每次 system_one 的 payload，用于验证分片与证据截断。"""

    def __init__(self, score: float = 0.9, fail_on_call: int | None = None):
        self.score = score
        self.fail_on_call = fail_on_call
        self.calls: list[dict] = []

    async def system_one(self, state, questions):
        self.calls.append({"state": state, "questions": dict(questions)})
        if self.fail_on_call is not None and len(self.calls) - 1 == self.fail_on_call:
            raise RuntimeError("jev down")
        return {k: {"noul": self.score, "is_true": True} for k in questions}


@pytest.mark.asyncio
async def test_citation_evidence_is_capped_and_prefers_the_hit_paragraph(monkeypatch):
    """单条证据只送被引用的那一段（<=400 字符），不再把 1200 字整块塞进判据。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    jev = _RecordingJev()
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: jev)

    ref = {
        "content": "父块正文" * 300,
        "child_chunk_text": "第9条 住宿费用限额：总监级及以上（M4+）A类城市 800 元/晚。",
    }
    await verify_citations(_Fallback(), "答案[1]", [ref], "住宿标准？")

    assert len(jev.calls) == 1
    instruction = jev.calls[0]["questions"]["cite_1"]["instructions"]
    assert "800 元/晚" in instruction, "被引用的精确命中文段必须完整保留"
    assert "已截断" not in instruction
    assert len(instruction) <= 600, f"判据过长会挤掉证据：{len(instruction)}"


@pytest.mark.asyncio
async def test_many_citations_are_sharded_into_small_requests(monkeypatch):
    """10 条引用必须切成 <=4 条一片的多次请求，避免单请求塞爆上下文。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    jev = _RecordingJev()
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: jev)

    refs = [{"content": f"证据{i}的正文内容", "child_chunk_text": ""} for i in range(1, 11)]
    answer = "答案" + "".join(f"[{i}]" for i in range(1, 11))
    _, bad, meta = await verify_citations(_Fallback(), answer, refs, "问题")

    assert len(jev.calls) == 3, f"10 条引用应切成 3 片，实际 {len(jev.calls)}"
    assert all(len(c["questions"]) <= 4 for c in jev.calls)
    assert meta["status"] == "jev_judged"
    assert bad == []


@pytest.mark.asyncio
async def test_failed_shard_escalates_instead_of_silently_passing(monkeypatch):
    """某一片 JEV 失败时，该片引用必须视为未知并升级 LLM，不能默认通过。"""
    monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
    jev = _RecordingJev(fail_on_call=1)
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: jev)
    fallback = _Fallback()

    refs = [{"content": f"证据{i}", "child_chunk_text": ""} for i in range(1, 11)]
    answer = "答案" + "".join(f"[{i}]" for i in range(1, 11))
    _, _, meta = await verify_citations(fallback, answer, refs, "问题")

    assert fallback.calls == 1, "分片失败必须走 LLM 审计"
    assert meta["status"] == "judged"


class TestJevScreensButDoesNotAccuse:
    """标定实测（48 例确定性样本，AUC 0.974）：grounded 最低 0.01、fabricated 最高 0.52 ——
    没有阈值能把两者完全分开，所以 JEV 只能当"筛子"，判定必须交给 LLM，
    否则会把正确引用标成"未找到支持"（实测发生过）。"""

    @pytest.mark.asyncio
    async def test_low_score_escalates_instead_of_accusing(self, monkeypatch):
        monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
        monkeypatch.setattr(
            "app.infra.jev_client.get_jev_client",
            lambda: _FakeJev({"cite_1": {"noul": 0.01}, "cite_2": {"noul": 0.02}}),
        )
        fallback = _Fallback(payload='{"unsupported": [2]}')

        answer, bad, meta = await verify_citations(
            fallback, "答案[1][2]", [{"content": "证据一"}, {"content": "证据二"}], "问题"
        )
        assert fallback.calls == 1, "低分必须升级 LLM，而不是直接下结论"
        assert meta["status"] == "judged"
        assert bad == [2], "结论只能来自 LLM 审计"
        assert "未能在当前知识库证据中找到支持" in answer

    @pytest.mark.asyncio
    async def test_high_scores_skip_the_llm_entirely(self, monkeypatch):
        monkeypatch.setattr(cv_module, "get_settings", lambda: _settings())
        monkeypatch.setattr(
            "app.infra.jev_client.get_jev_client",
            lambda: _FakeJev({"cite_1": {"noul": 0.99}, "cite_2": {"noul": 0.97}}),
        )
        fallback = _Fallback()

        answer, bad, meta = await verify_citations(
            fallback, "答案[1][2]", [{"content": "证据一"}, {"content": "证据二"}], "问题"
        )
        assert fallback.calls == 0, "高置信支持时不应再花钱调 LLM"
        assert meta["status"] == "jev_judged" and bad == [] and answer == "答案[1][2]"
