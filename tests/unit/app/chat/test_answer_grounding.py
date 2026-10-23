"""零成本落地校验：回答里的文档名/条款号必须能在本轮证据里找到。

背景（实证）：7 道不可答题里有 5 道编造了语料中根本不存在的文档与条款
（如《员工在职进修与专业资格考证补贴办法》第 5.1 条），而当时的引用校验只在
回答含 [n] 时才启动，且完全依赖 LLM/JEV 判断，没有任何确定性兜底。
"""

from __future__ import annotations

from app.chat.answer_grounding import audit_grounding, grounding_note

HANDBOOK = {
    "id": 1,
    "title": "01_华远科技集团员工手册.md",
    "document_name": "01_华远科技集团员工手册.md",
    "section_title": "第5条 试用期规定",
    "section_path": "第5条 试用期规定",
    "content": "第5条 试用期规定 劳动合同期限三个月以上不满一年的，试用期不得超过一个月。",
}


def test_clean_answer_passes() -> None:
    answer = "试用期不得超过一个月[1]。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is False
    assert report.issues == ()
    assert report.dangling_citations == ()
    assert report.unsupported_citations == ()


def test_dangling_citation_is_blocking() -> None:
    report = audit_grounding("试用期一个月[7]。", [HANDBOOK])

    assert report.dangling_citations == (7,)
    assert report.blocking is True
    assert 7 in report.unsupported_citations


def test_fabricated_document_is_blocking() -> None:
    answer = "按《员工在职进修与专业资格考证补贴办法》第5.1条，A 类城市全额报销[1]。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is True
    kinds = {i.kind for i in report.issues}
    assert "unknown_document" in kinds
    # 该句带 [1]，但证据里没有这份文档 -> 该引用不可信
    assert 1 in report.unsupported_citations


def test_partial_document_name_is_grounded() -> None:
    answer = "《员工手册》第5条规定了试用期上限。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is False


def test_negated_mention_is_not_a_claim() -> None:
    """诚实拒答会提到不存在的文档，不能被判成幻觉。"""
    answer = "知识库中未收录《员工在职进修与专业资格考证补贴办法》，无法确认相关标准。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is False


def test_clause_must_appear_in_the_cited_evidence() -> None:
    answer = "第5.1条规定住宿上限 800 元[1]。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is True
    assert any(i.kind == "unknown_clause" for i in report.issues)
    assert 1 in report.unsupported_citations


def test_clause_present_in_evidence_passes() -> None:
    answer = "第5条 规定了试用期上限[1]。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is False


def test_clause_without_citation_checks_all_evidence() -> None:
    answer = "第5条对试用期有规定。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is False


def test_no_citation_but_fabricated_document_is_blocking() -> None:
    answer = "根据《员工在职进修与专业资格考证补贴办法》，服务期满即可申请。"
    report = audit_grounding(answer, [HANDBOOK])

    assert report.blocking is True
    assert report.unsupported_citations == ()


def test_empty_references_make_every_citation_dangling() -> None:
    report = audit_grounding("答案[1]", [])

    assert report.dangling_citations == (1,)
    assert report.blocking is True


def test_reference_without_metadata_still_works() -> None:
    report = audit_grounding("答案[1]", [{"content": "试用期不得超过一个月"}])

    assert report.blocking is False


def test_grounding_note_names_the_offending_claims() -> None:
    report = audit_grounding("按《员工在职进修与专业资格考证补贴办法》第5.1条执行[1]。", [HANDBOOK])
    note = grounding_note(report)

    assert "员工在职进修与专业资格考证补贴办法" in note
    assert note.startswith("\n\n")


def test_grounding_note_is_empty_when_clean() -> None:
    assert grounding_note(audit_grounding("试用期一个月[1]。", [HANDBOOK])) == ""


_QUANT: dict = {
    "content": "第9条 住宿费用限额 9.1 总监级及以上 800元/晚 A类城市",
    "document_name": "02_差旅制度.md",
}


def test_uncited_quantitative_claim_is_reported() -> None:
    """数值句没有引用编号 ⇒ 不可溯源（只报告，不阻断）。"""
    report = audit_grounding("住宿上限是 800 元/晚，A 类城市。", [_QUANT])

    assert report.blocking is False
    assert report.uncited_claims == ("住宿上限是 800 元/晚",)


def test_cited_quantitative_claim_is_not_reported() -> None:
    report = audit_grounding("住宿上限是 800 元/晚[1]。", [_QUANT])

    assert report.uncited_claims == ()


def test_qualitative_sentence_is_not_reported() -> None:
    report = audit_grounding("试用期由劳动合同期限决定。", [HANDBOOK])

    assert report.uncited_claims == ()


class TestNumericMismatch:
    """数字落地：判报告知、不硬拦（可能是合理推导），但足以让 JEV 别放行。"""

    def test_tampered_number_is_reported_but_not_blocking(self) -> None:
        report = audit_grounding("总监级每日住宿上限 807 元[1]。", [HANDBOOK])

        assert report.blocking is False, "数字不一致不直接拦，交 LLM 复核"
        assert report.numeric_mismatches
        meta = report.to_meta()
        assert meta["numeric_mismatches"][0]["value"].startswith("807")

    def test_matching_number_is_clean(self) -> None:
        report = audit_grounding("试用期不得超过 1 个月[1]。", [HANDBOOK])

        assert report.numeric_mismatches == ()


def test_chinese_numeral_clause_matches_chinese_evidence():
    """证据写"第二条"，回答也写"第二条" —— 不能因为内部统一成阿拉伯数字就判成假条款。"""
    report = audit_grounding(
        "第二条 差旅住宿城市标准（已作废）[1]",
        [
            {
                "reference_id": 1,
                "content": "第二条 2022版差旅住宿城市标准（已作废） 出差人员住宿费实行限额。",
            }
        ],
    )
    assert report.issues == ()
    assert report.blocking is False


def test_chinese_numeral_mismatch_is_still_caught():
    report = audit_grounding(
        "第九条 住宿费用限额[1]",
        [{"reference_id": 1, "content": "第二条 差旅住宿城市标准（已作废）。"}],
    )
    assert [i.kind for i in report.issues] == ["unknown_clause"]
