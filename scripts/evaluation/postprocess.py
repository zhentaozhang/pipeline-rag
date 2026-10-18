"""评测侧的生成后处理复刻（P0-2）。

评测 runner 原本只做「检索 → 组装 → 一次生成」，跳过了生产执行器在生成之后的两步：
引用校验（`verify_citations`）与回答质量审核（`AnswerQualityChecker`）。
而这两步恰好是 JEV 能接管的全部位置——跳过它们，V3（JEV）与 V2 在评测里必然完全等价，
上一轮"V3 实测零差异"就是这么来的。

这里复刻同样的两步（不写库、不走 SSE），并把耗时与引用准确率带回评测结果。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.chat.citation_verifier import extract_citations


def citation_accuracy(answer: str, bad_refs: list[int]) -> float | None:
    """回答里被引用的编号中，有多少条被证据真正支持。

    - 没有引用 → None（不参与均值，避免"零引用"被当成满分或零分）
    - bad_refs 里没被正文引用的编号不影响分母
    """
    cited = {int(n) for n in extract_citations(answer or "")}
    if not cited:
        return None
    bad = cited & {int(n) for n in (bad_refs or [])}
    return (len(cited) - len(bad)) / len(cited)


@dataclass
class PostprocessResult:
    answer: str = ""
    bad_refs: list[int] = field(default_factory=list)
    citation_meta: dict[str, Any] = field(default_factory=dict)
    quality_passed: bool | None = None
    quality_score: float | None = None
    quality_feedback: str = ""
    citation_ms: float = 0.0
    quality_ms: float = 0.0


async def run_postprocess(
    *,
    question: str,
    answer: str,
    references: list[dict[str, Any]],
    fallback: Any,
    run_quality: bool = True,
) -> PostprocessResult:
    """按生产执行器的顺序跑引用校验与质量审核。"""
    from app.chat.citation_verifier import verify_citations

    result = PostprocessResult(answer=answer)

    t0 = time.perf_counter()
    try:
        verified, bad_refs, meta = await verify_citations(
            fallback=fallback,
            answer=answer,
            references=references,
            question=question,
        )
        result.answer = verified
        result.bad_refs = list(bad_refs or [])
        result.citation_meta = meta or {}
    except Exception as exc:  # noqa: BLE001 - 后处理失败不应让评测崩掉
        result.citation_meta = {"error": str(exc)[:200]}
    result.citation_ms = (time.perf_counter() - t0) * 1000

    if run_quality:
        from app.executors.rag import AnswerQualityChecker

        t1 = time.perf_counter()
        try:
            quality = await AnswerQualityChecker().check(question, result.answer)
            result.quality_passed = bool(quality.passed)
            result.quality_score = float(quality.score)
            result.quality_feedback = str(getattr(quality, "feedback", "") or "")
        except Exception as exc:  # noqa: BLE001
            result.quality_feedback = f"error: {str(exc)[:200]}"
        result.quality_ms = (time.perf_counter() - t1) * 1000

    return result


def references_from_evidence(
    evidences: list[Any], *, max_chars: int = 2000
) -> list[dict[str, Any]]:
    """把 Evidence 映射成生产执行器同款的 references 结构（供 verify_citations 使用）。"""
    refs: list[dict[str, Any]] = []
    for ev in evidences:
        content = getattr(ev, "content", "") or ""
        if not content:
            continue
        refs.append(
            {
                "id": getattr(ev, "reference_id", 0),
                "title": getattr(ev, "title", "") or "",
                "section_title": getattr(ev, "section_title", None),
                "document_name": getattr(ev, "document_name", "") or "",
                "source_type": getattr(ev, "source_type", "document"),
                "url": getattr(ev, "url", "") or "",
                "document_id": getattr(ev, "document_id", "") or "",
                "chunk_id": getattr(ev, "chunk_id", "") or "",
                "parent_block_id": getattr(ev, "parent_block_id", "") or "",
                "content": content[:max_chars],
            }
        )
    return refs
