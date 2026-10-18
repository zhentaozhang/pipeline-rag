"""回答落地校验（零成本确定性兜底）：文档名与条款号必须能在本轮证据里找到。

背景（实证）：7 道不可答题里有 5 道编造了语料中根本不存在的文档与条款
（如《员工在职进修与专业资格考证补贴办法》第 5.1 条）。当时的引用校验只在回答
含 ``[n]`` 时才启动，且完全依赖 LLM/JEV 打分——于是"没有引用、但编了一份文档"
这种最伤信任的失败模式完全没有兜底。

本模块只做**不含任何模型调用**的确定性检查，三个问句：

1. ``[n]`` 指向的编号是否存在？（悬空引用必然不成立）
2. 回答提到的《文档名》是否出现在本轮证据里？
3. 回答提到的"第 N 条"是否出现在**该句所引用**的证据里？（该句无引用时放宽到全部证据）

刻意保守的两条规则：

* 断言式提及才算：紧邻"未收录/未找到/没有/不存在……"等否定线索的提及视为
  诚实拒答，不判为幻觉（否则正确的"知识库中未找到《X》"会被误杀）。
* 只有**确定不成立**时才阻断；无法证明不成立的（例如证据里没有条款号但语义
  可能一致）不阻断，交给 LLM/JEV 审计。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_DOC_NAME_RE = re.compile(r"《([^》]{2,80})》")
_CLAUSE_RE = re.compile(r"第\s*(\d{1,3}(?:\.\d{1,3})?|[零一二三四五六七八九十]{1,3})\s*条")
_CITATION_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;\n])")
_CLAUSE_SPLIT_RE = re.compile(r"[，,、]")

# 量化断言：出现数字 + 计量单位/条款形式，这类句子最需要可溯源
_QUANT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:元|块|天|日|个月|月|年|%|％|次|小时|人|晚|公里|km|倍|万))"
    r"|(?:\d+(?:\.\d+)?\s*条)"
    r"|第\s*(?:\d{1,3}|[零一二三四五六七八九十]{1,3})\s*条"
)

_NEGATION_CUES = (
    "未收录",
    "未找到",
    "未提供",
    "未涉及",
    "未包含",
    "未规定",
    "未明确",
    "没有",
    "不存在",
    "无法核实",
    "无法确认",
    "未能核实",
    "无法找到",
    "未见",
    "暂无",
    "不包含",
)
_NEGATION_WINDOW = 14

_TEXT_KEYS = (
    "document_name",
    "section_title",
    "section_path",
    "title",
    "content",
    "child_chunk_text",
    "snippet",
    "excerpt",
)


@dataclass(frozen=True)
class GroundingIssue:
    """一条无法落到本轮证据上的断言。"""

    kind: str  # unknown_document | unknown_clause
    claim: str  # 形如 "《某办法》" / "第5.1条"
    citations: tuple[int, ...] = ()


@dataclass(frozen=True)
class GroundingReport:
    dangling_citations: tuple[int, ...] = ()
    issues: tuple[GroundingIssue, ...] = ()
    # 含数值/条款但没有任何引用编号的句子（可溯源性问题，只报告不阻断）
    uncited_claims: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return bool(self.dangling_citations or self.issues)

    @property
    def unsupported_citations(self) -> tuple[int, ...]:
        """确定性可判定的不可信引用编号（悬空 + 落在问题句里的引用）。"""
        out: list[int] = []
        for n in self.dangling_citations:
            if n not in out:
                out.append(n)
        for issue in self.issues:
            for n in issue.citations:
                if n not in out:
                    out.append(n)
        return tuple(out)

    def to_meta(self) -> dict[str, Any]:
        return {
            "dangling_citations": list(self.dangling_citations),
            "uncited_claims": [c[:80] for c in self.uncited_claims],
            "issues": [
                {"kind": i.kind, "claim": i.claim, "citations": list(i.citations)}
                for i in self.issues
            ],
        }


def _normalize(text: str) -> str:
    """去空白/标点/下划线并小写，用于"是否出现"的包含判定。"""
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _ref_blob(ref: Mapping[str, Any] | Any) -> str:
    if isinstance(ref, Mapping):
        return " ".join(str(ref.get(k) or "") for k in _TEXT_KEYS)
    return str(ref)


def _ref_doc_labels(ref: Mapping[str, Any] | Any) -> set[str]:
    """从一条证据里派生可能的文档名写法（含去扩展名/去序号前缀）。"""
    if not isinstance(ref, Mapping):
        return set()
    labels: set[str] = set()
    for key in ("document_name", "title"):
        raw = str(ref.get(key) or "").strip()
        if not raw:
            continue
        labels.add(_normalize(raw))
        stem = raw.rsplit("/", 1)[-1]
        for suffix in (".md", ".pdf", ".docx", ".txt", ".doc"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        labels.add(_normalize(stem))
        labels.add(_normalize(re.sub(r"^[\d_\-\s]+", "", stem)))
    labels.discard("")
    return {label for label in labels if len(label) >= 2}


def _citation_ids(
    references: Sequence[Mapping[str, Any] | Any],
) -> dict[int, Mapping[str, Any] | Any]:
    """引用编号 -> 证据。reference_id 与位置一致时直接用 id，否则退回 1..N。"""
    refs = list(references)
    explicit: list[int] = []
    for ref in refs:
        raw = ref.get("id") if isinstance(ref, Mapping) else None
        try:
            explicit.append(int(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            explicit = []
            break
    if explicit and len(explicit) == len(refs):
        return dict(zip(explicit, refs, strict=False))
    return {i + 1: ref for i, ref in enumerate(refs)}


def _sentences(answer: str) -> list[str]:
    parts = [s for s in _SENTENCE_RE.split(answer or "") if s.strip()]
    return parts or [answer or ""]


def _negated(sentence: str, start: int, end: int) -> bool:
    """提及本身是否被否定。

    只看提及两侧的窗口、**不含提及自身**——否则文档名叫"不存在的办法"时，
    名字里自带的"不存在"会把每一处提及都判成否定。
    """
    before = sentence[max(0, start - _NEGATION_WINDOW) : start]
    after = sentence[end : end + _NEGATION_WINDOW]
    window = before + "\x00" + after
    return any(cue in window for cue in _NEGATION_CUES)


def _clause(num: str) -> int | None:
    try:
        return int(num)
    except ValueError:
        from app.rag.query_tokens import cn_to_int

        return cn_to_int(num)


def _clause_matches(num: str, blob: str) -> bool:
    if "." in num:
        return _normalize(num) in _normalize(blob) or _normalize(f"第{num}条") in _normalize(blob)
    value = _clause(num)
    if value is None:
        return True  # 解析不了就不判负（保守）
    return _normalize(f"第{value}条") in _normalize(blob)


def _doc_matches(name: str, refs: Sequence[Mapping[str, Any] | Any]) -> bool:
    target = _normalize(name)
    if len(target) < 2:
        return True
    for ref in refs:
        for label in _ref_doc_labels(ref):
            if target in label or label in target:
                return True
        if target in _normalize(_ref_blob(ref)):
            return True
    return False


def audit_grounding(
    answer: str,
    references: Sequence[Mapping[str, Any] | Any] | None,
) -> GroundingReport:
    """确定性检查回答里的引用编号、文档名、条款号能否落到本轮证据上。"""
    refs = list(references or [])
    by_id = _citation_ids(refs)

    dangling: list[int] = []
    issues: list[GroundingIssue] = []
    uncited: list[str] = []

    for sentence in _sentences(answer):
        cited = []
        for m in _CITATION_RE.finditer(sentence):
            n = int(m.group(1))
            if n in by_id:
                if n not in cited:
                    cited.append(n)
            elif n not in dangling:
                dangling.append(n)
        # 量化断言按"逗号级片段"判定：一个长句里混了带引用和不带引用的数值很常见
        for fragment in _CLAUSE_SPLIT_RE.split(sentence):
            frag = fragment.strip()
            if not frag or _CITATION_RE.search(frag):
                continue
            if _QUANT_RE.search(frag):
                uncited.append(frag)
        scope = [by_id[n] for n in cited] if cited else refs

        for m in _DOC_NAME_RE.finditer(sentence):
            name = m.group(1).strip()
            if not name or _negated(sentence, m.start(), m.end()):
                continue
            if _doc_matches(name, scope) or (cited and _doc_matches(name, refs)):
                continue
            issues.append(GroundingIssue("unknown_document", f"《{name}》", tuple(cited)))

        for m in _CLAUSE_RE.finditer(sentence):
            num = m.group(1)
            if _negated(sentence, m.start(), m.end()):
                continue
            if any(_clause_matches(num, _ref_blob(ref)) for ref in scope):
                continue
            if cited and any(_clause_matches(num, _ref_blob(ref)) for ref in refs):
                continue
            label = f"第{num}条"
            issues.append(GroundingIssue("unknown_clause", label, tuple(cited)))

    return GroundingReport(
        dangling_citations=tuple(dangling),
        issues=tuple(issues),
        uncited_claims=tuple(uncited),
    )


def needs_citation_check(
    answer: str,
    references: Sequence[Mapping[str, Any] | Any] | None,
) -> bool:
    """回答是否值得走一次引用校验。

    旧门禁是 ``bool(extract_citations(answer))``——于是"没有 [n] 但编造了一份文档"
    这种失败模式直接跳过校验。现在两种触发：
    ① 回答里有 ``[n]``；② 确定性检查已经判负（悬空引用/不存在的文档名或条款号）。
    """
    if _CITATION_RE.search(answer or ""):
        return True
    return audit_grounding(answer, references).blocking


def grounding_note(report: GroundingReport) -> str:
    """把确定性判负的结论写成一句用户可见的尾注（不改写正文）。"""
    if not report.blocking:
        return ""
    parts: list[str] = []
    claims: list[str] = []
    for issue in report.issues:
        if issue.claim not in claims:
            claims.append(issue.claim)
    if claims:
        parts.append(f"回答中提到的 {'、'.join(claims[:3])} 未在本次检索到的知识库证据中出现")
    if report.dangling_citations:
        refs = "、".join(f"[{n}]" for n in report.dangling_citations)
        parts.append(f"引用编号 {refs} 没有对应的证据")
    detail = "；".join(parts)
    return f"\n\n（注：{detail}，相关内容无法核实，请以官方文件为准。）"
