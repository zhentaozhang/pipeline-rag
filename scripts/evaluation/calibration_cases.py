"""构造式标定集：标签由构造保证，不需要人工标注，也不许用 LLM 判分来打标签。

用法：从真实语料里取 chunk，按 6 种方式加工出"答案 + 证据"，每种的标签在构造时就已确定：

- ``verbatim``      答案摘录自证据         -> 应判定"被支持"
- ``topic_drift``   答案摘录自同文档别的条款 -> 不应被支持（相关但非所需）
- ``doc_swap``      答案摘录自另一份文档     -> 不应被支持（完全无关）
- ``number_tamper`` 答案里改掉一个数字       -> 不应被支持（judge 的已知盲区）
- ``negation_flip`` 答案把"禁止/不得"翻成"允许" -> 不应被支持（极性翻转）
- ``condition_drop`` 答案删掉适用条件         -> 不应被支持（过度泛化）

这些正好覆盖"引用核验"最需要区分的失败模式，且全部来自项目自己的语料，
零外部依赖、零 API 费用。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

CALIBRATION_KINDS: tuple[str, ...] = (
    "verbatim",
    "topic_drift",
    "doc_swap",
    "number_tamper",
    "negation_flip",
    "condition_drop",
)

SUPPORTED_KINDS: frozenset[str] = frozenset({"verbatim"})

_MIN_SENTENCE = 15
_MAX_EVIDENCE = 1200

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUALIFIER_RE = re.compile(
    r"M[1-9]\+?|P[1-9](?:-\d+)?|[A-D]\s?类城市"
    r"|总监级|经理级|主管级|员工级|高管级"
    r"|\d+\s*(?:小时|日内|日|天|个月|人次|万元|元)"
)
_PROHIBITION_RE = re.compile(r"禁止|不得|严禁|不允许")
_FLIP = {"禁止": "允许", "不得": "可以", "严禁": "允许", "不允许": "允许"}


@dataclass(frozen=True)
class CalibrationCase:
    """一条构造好的标定样本。``gold_chunk_id`` 是"本应被引用的证据"。"""

    case_id: str
    kind: str
    criterion: str
    expected_supported: bool
    question: str
    answer: str
    evidence: str
    chunk_id: str
    document_name: str
    gold_chunk_id: str
    gold_document_name: str


def _clean(text: str) -> str:
    text = text.replace("**", "").replace("###", "").replace("##", "")
    return re.sub(r"[ \t]+", " ", text).strip()


_NUMBERING_RE = re.compile(r"^\s*\d+(?:\.\d+)*\s*")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？\n]+", _clean(text))
    out: list[str] = []
    for part in parts:
        # 去掉"9.1"/"第10条"这类编号前缀，让答案读起来像一句真实论断
        stripped = _NUMBERING_RE.sub("", part).strip()
        if len(stripped) >= _MIN_SENTENCE:
            out.append(stripped)
    return out


def _question_for(chunk: dict) -> str:
    section = (chunk.get("section_path") or "").strip()
    if section:
        return f"关于「{section}」，制度是怎么规定的？"
    return "制度里对此是怎么规定的？"


_PROTECTED_NUMBER_RE = re.compile(r"[A-Za-z]{1,3}\d+(?:\+)?|\d+\s*类")


def _tamper_number(sentence: str, evidence: str) -> str | None:
    """把句子里的第一个"真数值"换成别处没出现过的值；改不动返回 None。

    ``M4+``/``P6``/``2 类`` 这类编号里的数字不是可篡改的量，必须先屏蔽，
    否则会把职级 ``M4+`` 改成 ``M11+``——那不是数值错误样本，是胡话样本。
    """
    masked = _PROTECTED_NUMBER_RE.sub(lambda m: "\x00" * len(m.group(0)), sentence)
    seen = set(_NUMBER_RE.findall(evidence))
    for match in _NUMBER_RE.finditer(masked):
        raw = match.group(0)
        if raw != sentence[match.start() : match.end()]:
            continue
        base = float(raw)
        for delta in (7, 13, 29, 41):
            candidate = int(base + delta) if base == int(base) else round(base + delta, 1)
            text = str(candidate)
            if text not in seen:
                return sentence[: match.start()] + text + sentence[match.end() :]
    return None


def _flip_polarity(sentence: str) -> str | None:
    for word, replacement in _FLIP.items():
        if word in sentence:
            flipped = sentence.replace(word, replacement)
            if not _PROHIBITION_RE.search(flipped):
                return flipped
    return None


def _drop_condition(sentence: str) -> str | None:
    """删掉含"职级/城市分类"限定词的整个分句，得到过度泛化的说法。"""
    if not _QUALIFIER_RE.search(sentence):
        return None
    parts = [p for p in re.split(r"[，,]", sentence) if p.strip()]
    if len(parts) < 2:
        return None
    kept = [p for p in parts if not _QUALIFIER_RE.search(p)]
    if not kept or len(kept) == len(parts):
        return None
    return "，".join(p.strip() for p in kept)


def _case_id(kind: str, index: int, chunk_id: str) -> str:
    return f"{kind}-{index:03d}-{chunk_id}"


def build_cases(
    chunks: list[dict],
    *,
    per_kind: int = 40,
    seed: int = 42,
) -> list[CalibrationCase]:
    """按 kind 构造标定样本；某类候选不足时诚实返回更少，不硬凑。"""
    if not chunks:
        raise ValueError("标定集需要至少一个 chunk")

    usable = [
        c for c in chunks if c.get("chunk_id") and len(_clean(c.get("chunk_text") or "")) >= 30
    ]
    if not usable:
        raise ValueError("没有可用于构造标定样本的 chunk（正文过短）")

    rng = random.Random(seed)
    ordered = list(usable)
    rng.shuffle(ordered)

    by_doc: dict[str, list[dict]] = {}
    for chunk in ordered:
        by_doc.setdefault(str(chunk.get("document_id") or chunk["chunk_id"]), []).append(chunk)

    cases: list[CalibrationCase] = []
    counters: dict[str, int] = {kind: 0 for kind in CALIBRATION_KINDS}

    for index, gold in enumerate(ordered):
        doc_key = str(gold.get("document_id") or gold["chunk_id"])
        siblings = [c for c in by_doc.get(doc_key, []) if c["chunk_id"] != gold["chunk_id"]]
        others = [c for c in ordered if str(c.get("document_id") or c["chunk_id"]) != doc_key]
        gold_text = _clean(gold.get("chunk_text") or "")[:_MAX_EVIDENCE]
        sentences = _sentences(gold_text)
        if not sentences:
            continue

        def emit(
            kind: str,
            answer: str,
            evidence: str,
            evidence_chunk: dict,
            gold: dict = gold,
        ) -> None:
            if counters[kind] >= per_kind:
                return
            counters[kind] += 1
            cases.append(
                CalibrationCase(
                    case_id=_case_id(kind, counters[kind], gold["chunk_id"]),
                    kind=kind,
                    criterion="citation_support",
                    expected_supported=kind in SUPPORTED_KINDS,
                    question=_question_for(gold),
                    answer=answer,
                    evidence=evidence,
                    chunk_id=str(evidence_chunk["chunk_id"]),
                    document_name=str(evidence_chunk.get("document_name") or ""),
                    gold_chunk_id=str(gold["chunk_id"]),
                    gold_document_name=str(gold.get("document_name") or ""),
                )
            )

        # verbatim：答案就是证据里的原话
        emit("verbatim", sentences[0], gold_text, gold)

        # topic_drift：同一份文档的别的条款
        if siblings:
            drift = siblings[index % len(siblings)]
            emit(
                "topic_drift",
                sentences[0],
                _clean(drift.get("chunk_text") or "")[:_MAX_EVIDENCE],
                drift,
            )

        # doc_swap：另一份文档
        if others:
            swapped = others[(index * 7 + 1) % len(others)]
            emit(
                "doc_swap",
                sentences[0],
                _clean(swapped.get("chunk_text") or "")[:_MAX_EVIDENCE],
                swapped,
            )

        if counters["number_tamper"] < per_kind:
            for sentence in sentences:
                tampered = _tamper_number(sentence, gold_text)
                if tampered:
                    emit("number_tamper", tampered, gold_text, gold)
                    break

        if counters["negation_flip"] < per_kind:
            for sentence in sentences:
                flipped = _flip_polarity(sentence)
                if flipped:
                    emit("negation_flip", flipped, gold_text, gold)
                    break

        if counters["condition_drop"] < per_kind:
            for sentence in sentences:
                dropped = _drop_condition(sentence)
                if dropped:
                    emit("condition_drop", dropped, gold_text, gold)
                    break

        if all(counters[kind] >= per_kind for kind in CALIBRATION_KINDS):
            break

    return cases


def case_counts(cases: list[CalibrationCase]) -> dict[str, int]:
    counts = {kind: 0 for kind in CALIBRATION_KINDS}
    for case in cases:
        counts[case.kind] = counts.get(case.kind, 0) + 1
    return counts
