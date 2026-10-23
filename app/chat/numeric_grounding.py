"""确定性落地校验（零模型调用）：回答里的数字与极性，必须能在它自己引用的证据里对上。

两条规则都来自实测：
- **数字**：judge 对"措辞不变、只改数字"几乎无感（faithfulness 0.986→0.56、
  answer_correctness 0.742→0.289），而题库 20/85 是数值限额题；
  标定集上"全部数字令牌必须出现在证据里"捕获 97.5% 的改数字样本、0% 误报。
- **极性**：判据模型对"禁止→允许"同样不敏感（AUC 0.732，生产阈值下 52.5% 被放行）；
  "证据含禁止性表述 + 回答只说可以/允许且无否定词"捕获 77.5%、0% 误报。

保守原则：只报告、不阻断 —— 命中只会让"高置信跳过 LLM"失效，强制走一次复核。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# 单位表：长的放前面，避免"万元"被"元"吃掉
_UNITS = (
    "万元",
    "千米",
    "公里",
    "个月",
    "分钟",
    "小时",
    "元",
    "天",
    "日",
    "月",
    "年",
    "晚",
    "次",
    "人",
    "个",
    "倍",
    "岁",
    "%",
    "％",
)
_UNIT_ALT = "|".join(re.escape(u) for u in _UNITS)
_CN_UNIT_ALT = "|".join(re.escape(u) for u in _UNITS if u not in {"%", "％"})

_QUANT_RE = re.compile(rf"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*({_UNIT_ALT})")
_CN_QUANT_RE = re.compile(rf"([一二三四五六七八九十百千两]+)\s*({_CN_UNIT_ALT})")
_PROTECTED_TOKEN_RE = re.compile(r"[A-Za-z]{1,3}\d+(?:\+)?|\d+\s*类|第\s*\d+\s*条")
_NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d+(?:\.\d+)?)(?![A-Za-z0-9])")
_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")
_CLAUSE_SPLIT_RE = re.compile(r"[，,、]")
_ASIDE_MARKERS = ("另", "此外", "同时", "另外", "附带", "补充")

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", "0123456789.")
_THOUSANDS_RE = re.compile(r"(?<=\d)[,，](?=\d{3}(?!\d))")
_MONEY_TO_YUAN = {"万元": 10000.0}

_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

# 极性：证据禁止、回答放行
_EVIDENCE_PROHIBITION_RE = re.compile(r"禁止|不得|严禁|不允许|不予受理")
_PERMIT_RE = re.compile(r"可以|允许|可申请|有权|准予|可享受")
_DENIAL_RE = re.compile(r"不|未|无|禁止|严禁|拒绝|避免")


@dataclass(frozen=True)
class NumericIssue:
    """一个"回答里出现了证据中没有的量"的问题。"""

    sentence: str
    raw: str
    ref_ids: list[int]
    reason: str = "not_in_evidence"


@dataclass(frozen=True)
class PolarityIssue:
    """一个"证据禁止、回答却说可以"的问题。"""

    sentence: str
    ref_ids: list[int]
    reason: str = "polarity_flip"


def _normalize(value: float, unit: str) -> float:
    return value * _MONEY_TO_YUAN.get(unit, 1.0)


def _cn_to_number(text: str) -> float | None:
    """中文数字转阿拉伯数字（制度原文大量用"三个月""十五日"这类写法）。"""
    total = 0
    pending = 0
    for ch in text:
        if ch in _CN_DIGITS:
            pending = _CN_DIGITS[ch]
        elif ch == "十":
            total += (pending or 1) * 10
            pending = 0
        elif ch == "百":
            total += (pending or 1) * 100
            pending = 0
        elif ch == "千":
            total += (pending or 1) * 1000
            pending = 0
        else:
            return None
    return float(total + pending) if total + pending else None


def _cn_quantities(text: str) -> list[tuple[float, str, str]]:
    out: list[tuple[float, str, str]] = []
    for match in _CN_QUANT_RE.finditer(text or ""):
        value = _cn_to_number(match.group(1))
        if value is None:
            continue
        unit = match.group(2)
        out.append((_normalize(value, unit), unit, match.group(0).strip()))
    return out


def extract_quantities(text: str) -> list[tuple[float, str, str]]:
    """抽取 (归一化数值, 单位, 原文片段)。裸数字与条款号不算量。"""
    cleaned = _CITATION_RE.sub(" ", text or "")
    cleaned = cleaned.translate(_FULLWIDTH_DIGITS)
    cleaned = _THOUSANDS_RE.sub("", cleaned)
    out: list[tuple[float, str, str]] = []
    for match in _QUANT_RE.finditer(cleaned):
        start = match.start()
        if start > 0 and cleaned[start - 1] == "第":
            continue
        out.append(
            (
                _normalize(float(match.group(1)), match.group(2)),
                match.group(2),
                match.group(0).strip(),
            )
        )
    out.extend(_cn_quantities(cleaned))
    return out


def token_values(text: str) -> set[float]:
    """取一段文本的全部数值（含中文数字与万元换算）。

    为什么不只看"带单位的量"：语料里大量数字带的是"工作日/人天/届"这类未登记单位，
    只看单位会漏掉 82% 的改数字样本（捕获率 17.5%）；改成"全部数字令牌"后
    同一批样本捕获率 97.5%，正确摘录的误报率仍为 0%。
    """
    cleaned = (text or "").translate(_FULLWIDTH_DIGITS)
    cleaned = _THOUSANDS_RE.sub("", _CITATION_RE.sub(" ", cleaned))
    masked = _PROTECTED_TOKEN_RE.sub(" ", cleaned)
    values: set[float] = set()
    for match in _NUM_TOKEN_RE.finditer(masked):
        value = float(match.group(1))
        values.add(value)
        if "万元" in masked[match.end() : match.end() + 3]:
            values.add(value * 10000.0)
    for value, _unit, _raw in _cn_quantities(cleaned):
        values.add(value)
    return values


def _reference_ref_id(reference: object, index: int) -> int:
    if isinstance(reference, dict):
        raw = reference.get("reference_id")
    else:
        raw = getattr(reference, "reference_id", None)
    return int(raw) if isinstance(raw, int | str) and str(raw).isdigit() else index + 1


def _evidence_blob(reference: object) -> str:
    if isinstance(reference, dict):
        child = str(reference.get("child_chunk_text") or "")
        content = str(reference.get("content") or "")
    else:
        child = str(getattr(reference, "child_chunk_text", "") or "")
        content = str(getattr(reference, "content", "") or "")
    return f"{child}\n{content}"


def _iter_cited_fragments(answer: str) -> list[tuple[str, list[int]]]:
    """把回答切成"带引用的逗号级片段"，并给出该片段引用的编号。

    同一句里没有自己引用的片段默认算在被引用的那句话下（"上限 807 元，含税[1]"），
    但"另有/此外…"这类补充说明不参与判定。
    """
    out: list[tuple[str, list[int]]] = []
    for sentence in _SENTENCE_SPLIT_RE.split(answer or ""):
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_refs = sorted({int(n) for n in _CITATION_RE.findall(sentence)})
        if not sentence_refs:
            continue
        for fragment in _CLAUSE_SPLIT_RE.split(sentence):
            fragment = fragment.strip()
            if not fragment:
                continue
            ref_ids = sorted({int(n) for n in _CITATION_RE.findall(fragment)}) or sentence_refs
            if not ref_ids:
                continue
            if not _CITATION_RE.search(fragment) and fragment.startswith(_ASIDE_MARKERS):
                continue
            out.append((fragment, ref_ids))
    return out


def _by_ref(references: Sequence[object]) -> dict[int, str]:
    return {_reference_ref_id(ref, i): _evidence_blob(ref) for i, ref in enumerate(references)}


def _normalize_answer(answer: str) -> str:
    return _THOUSANDS_RE.sub("", (answer or "").translate(_FULLWIDTH_DIGITS))


def numeric_issues(
    answer: str, references: list[dict] | list[object], *, max_issues: int = 8
) -> list[NumericIssue]:
    """逐片段检查"每个量是否出现在它引用的证据里"。"""
    if not answer or not references:
        return []
    evidence = _by_ref(references)
    issues: list[NumericIssue] = []
    for fragment, ref_ids in _iter_cited_fragments(_normalize_answer(answer)):
        available: set[float] = set()
        missing_refs: list[int] = []
        for ref_id in ref_ids:
            if ref_id in evidence:
                available |= token_values(evidence[ref_id])
            else:
                missing_refs.append(ref_id)
        for value in sorted(token_values(fragment)):
            if value in available:
                continue
            issues.append(
                NumericIssue(
                    sentence=fragment,
                    raw=f"{value:g}",
                    ref_ids=ref_ids,
                    reason="missing_reference"
                    if not available and missing_refs
                    else "not_in_evidence",
                )
            )
            if len(issues) >= max_issues:
                return issues
    return issues


def polarity_issues(
    answer: str, references: list[dict] | list[object], *, max_issues: int = 4
) -> list[PolarityIssue]:
    """证据里有禁止性表述，而引用它的片段只说"可以/允许"且没有任何否定词。"""
    if not answer or not references:
        return []
    evidence = _by_ref(references)
    issues: list[PolarityIssue] = []
    for fragment, ref_ids in _iter_cited_fragments(_normalize_answer(answer)):
        blob = "\n".join(evidence[r] for r in ref_ids if r in evidence)
        if not _EVIDENCE_PROHIBITION_RE.search(blob):
            continue
        if not _PERMIT_RE.search(fragment) or _DENIAL_RE.search(fragment):
            continue
        issues.append(PolarityIssue(sentence=fragment, ref_ids=ref_ids))
        if len(issues) >= max_issues:
            return issues
    return issues


def caution_note(
    issues: Sequence[NumericIssue],
    polarity: Sequence[PolarityIssue],
    *,
    limit: int = 2,
) -> str:
    """把确定性判负写成一句用户可见的尾注（只提示，不改写正文、不阻断）。

    尾注里刻意不写 ``[n]`` 形式，改用"证据 n"——否则尾注自己的方括号会被下游
    当成新的引用编号，凭空造出一条引用。
    """
    parts: list[str] = []
    for issue in list(issues)[:limit]:
        refs = "、".join(f"证据 {r}" for r in issue.ref_ids) or "所引证据"
        parts.append(f"数值 {issue.raw} 未出现在 {refs} 中")
    remaining = max(0, limit - len(parts))
    for p_issue in list(polarity)[:remaining]:
        refs = "、".join(f"证据 {r}" for r in p_issue.ref_ids) or "所引证据"
        parts.append(f"{refs} 为禁止性规定而回答表述为允许")
    if not parts:
        return ""
    body = "；".join(f"· {p}" for p in parts)
    return f"\n\n（注：以下内容未能在所引证据中核实，请核对原文：{body}。）"
