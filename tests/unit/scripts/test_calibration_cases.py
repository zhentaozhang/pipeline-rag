"""标定集必须"构造即标签"：正负样本的答案对错在构造时已确定，不依赖任何模型判断。

这里钉的是构造的正确性 —— 改数字必须真改到数字、翻极性必须真翻转、
删条件必须真删掉限定词，否则标定集的标签就是假的。
"""

from __future__ import annotations

import re

import pytest

from scripts.evaluation.calibration_cases import (
    CALIBRATION_KINDS,
    build_cases,
)


def _chunk(cid, doc, section, text):
    return {
        "chunk_id": cid,
        "document_id": doc,
        "document_name": f"{doc}_制度.md",
        "section_path": section,
        "chunk_text": text,
    }


CHUNKS = [
    _chunk(
        "c1",
        "docA",
        "第9条 住宿费用限额",
        "### 第9条 住宿费用限额\n\n**9.1** 总监级及以上（M4+）在 A 类城市出差，每日住宿上限为 800 元/晚，含税。\n"
        "**9.2** 员工级在 B 类城市出差，每日住宿上限为 450 元/晚。",
    ),
    _chunk(
        "c2",
        "docA",
        "第10条 餐饮补贴",
        "### 第10条 餐饮补贴\n\n出差期间每日餐饮补贴为 100 元，无需发票。",
    ),
    _chunk(
        "c3",
        "docB",
        "第3条 保密义务",
        "### 第3条 保密义务\n\n员工禁止将客户数据带离办公场所，禁止使用私人邮箱发送。",
    ),
    _chunk(
        "c4",
        "docB",
        "第4条 加班调休",
        "### 第4条 加班调休\n\n加班满 4 小时可申请调休，调休需在 30 日内使用。",
    ),
    _chunk(
        "c5",
        "docC",
        "第6条 报销时限",
        "### 第6条 报销时限\n\n费用发生后 60 日内必须提交报销单，逾期不予受理。",
    ),
]


def _by_kind(cases, kind):
    return [c for c in cases if c.kind == kind]


def test_all_kinds_present_and_counts_match():
    cases = build_cases(CHUNKS, per_kind=2)
    assert {c.kind for c in cases} == set(CALIBRATION_KINDS)
    for kind in CALIBRATION_KINDS:
        assert len(_by_kind(cases, kind)) >= 1, f"{kind} 没有构造出样本"


def test_labels_follow_construction():
    cases = build_cases(CHUNKS, per_kind=2)
    for c in cases:
        assert c.expected_supported is (c.kind == "verbatim")


def test_verbatim_answer_really_appears_in_the_evidence():
    for c in _by_kind(build_cases(CHUNKS, per_kind=3), "verbatim"):
        core = re.sub(r"\s+", "", c.answer)
        assert core and core in re.sub(r"\s+", "", c.evidence)


def test_number_tamper_really_changes_a_number():
    cases = _by_kind(build_cases(CHUNKS, per_kind=3), "number_tamper")
    assert cases
    for c in cases:
        ev_numbers = set(re.findall(r"\d+(?:\.\d+)?", c.evidence))
        ans_numbers = set(re.findall(r"\d+(?:\.\d+)?", c.answer))
        changed = ans_numbers - ev_numbers
        assert changed, f"数字没被改动：{c.answer}"
        # 改动后的数字不能是原文里本来就有的另一个数字（避免"只是换了句子"）
        assert any(n not in ev_numbers for n in changed)


def test_negation_flip_really_inverts_polarity():
    cases = _by_kind(build_cases(CHUNKS, per_kind=3), "negation_flip")
    assert cases
    for c in cases:
        assert re.search(r"禁止|不得|严禁|不允许", c.evidence), "证据必须含禁止性表述"
        assert re.search(r"允许|可以|应当可以", c.answer), "答案必须翻成许可性表述"
        assert not re.search(r"禁止|不得|严禁|不允许", c.answer)


QUALIFIER_PROBE = re.compile(
    r"M[1-9]\+?|P[1-9](?:-\d+)?|[A-D]\s?类城市"
    r"|总监级|经理级|主管级|员工级|高管级"
    r"|\d+\s*(?:小时|日内|日|天|个月|人次|万元|元)"
)


def test_condition_drop_really_removes_the_qualifier():
    cases = _by_kind(build_cases(CHUNKS, per_kind=3), "condition_drop")
    assert cases
    for c in cases:
        assert len(c.answer) < len(c.evidence)
        dropped = QUALIFIER_PROBE.findall(c.evidence)
        kept = QUALIFIER_PROBE.findall(c.answer)
        # 原文有多少限定词，答案必须少掉至少一个（否则只是换了句子，不是"删条件"）
        assert len(kept) < len(dropped), f"没删掉任何限定条件：{c.answer}"


def test_hard_negatives_come_from_other_chunks_or_documents():
    cases = build_cases(CHUNKS, per_kind=3)
    drift = _by_kind(cases, "topic_drift")
    swap = _by_kind(cases, "doc_swap")
    assert drift and swap
    for c in drift:
        assert c.chunk_id != c.gold_chunk_id
        assert c.document_name == c.gold_document_name
    for c in swap:
        assert c.document_name != c.gold_document_name


def test_same_seed_is_idempotent():
    a = build_cases(CHUNKS, per_kind=3, seed=7)
    b = build_cases(CHUNKS, per_kind=3, seed=7)
    assert [(c.case_id, c.answer) for c in a] == [(c.case_id, c.answer) for c in b]


def test_rejects_empty_corpus():
    with pytest.raises(ValueError):
        build_cases([], per_kind=2)
