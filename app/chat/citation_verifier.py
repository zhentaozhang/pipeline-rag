"""引用验证器（017 生成侧质量修复：引用纪律的代码级兜底）。

背景（实证）：prompt 引用纪律对顽固幻觉失效——"辞职"问题在证据只有试用期条款时，
模型仍回答"辞职须提前30天书面通知 [1]"（假引用）。LLM 自检在生成后逐引用核对证据，
不支持的引用在回答末尾追加诚实说明（不改写已流式输出的正文）。

成本：每轮 1 次轻量 LLM 调用（仅当回答含引用且证据非空时触发）。
开关：RAG_CITATION_VERIFY_ENABLED（默认开，延迟敏感场景可关）。
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citations(answer: str) -> list[int]:
    """提取回答中的引用编号（保序去重）"""
    seen: list[int] = []
    for m in CITATION_RE.finditer(answer):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def _reference_content(ref: dict[str, Any] | Any, fallback_id: int, max_chars: int = 1200) -> str:
    """从 reference 条目提取证据文本，优先精确匹配子块并携带父块上下文"""
    if isinstance(ref, dict):
        child_text = (ref.get("child_chunk_text") or "").strip()
        full_content = (
            ref.get("content")
            or ref.get("excerpt")
            or ref.get("snippet")
            or ref.get("chunk_text")
            or ref.get("title")
            or ""
        ).strip()

        if child_text and full_content and child_text != full_content:
            if child_text in full_content:
                text = full_content
            else:
                text = f"【精确命中段落】：{child_text}\n【上下文】：{full_content}"
        else:
            text = child_text or full_content or f"(证据 {fallback_id}，无文本)"

        return text[:max_chars]
    return str(ref)[:max_chars]


async def verify_citations(
    fallback: Any,
    answer: str,
    references: list[dict[str, Any] | Any],
    question: str = "",
) -> tuple[str, list[int], dict[str, Any]]:
    """验证回答中每个 [n] 引用是否被对应证据支持。

    返回 (修正后 answer, 不支持/无法核实的引用编号列表, 元信息)。
    仅追加说明，不改写正文（正文已流式发出）。
    """
    refs = extract_citations(answer)
    if not refs:
        return answer, [], {"status": "no_citation"}
    if not references:
        note = "\n\n（注：回答中标注的引用未能从当前知识库证据核实，请以官方文件为准。）"
        return answer + note, refs, {"status": "no_evidence"}

    # 优先采用 JEV System 1 并行 Noul 原语进行精准事实核验（零格式解析错误、毫秒级响应）
    settings = get_settings()
    jev_cfg = getattr(settings, "jev", None)
    if jev_cfg and getattr(jev_cfg, "citation_verify_enabled", True):
        try:
            from app.infra.jev_client import get_jev_client

            jev = get_jev_client()
            evidence_map = {
                i + 1: _reference_content(r, i + 1, max_chars=1200)
                for i, r in enumerate(references)
            }
            questions = {
                f"cite_{ref_n}": {
                    "type": "noul",
                    "instructions": (
                        f"回答中带有 [{ref_n}] 编号的引用论断，是否确实被以下证据内容直接支持（无推测、无捏造）？\n"
                        f"证据[{ref_n}]：{evidence_map.get(ref_n, '（该引用编号无对应证据内容）')}"
                    ),
                }
                for ref_n in refs
            }
            state = f"用户问题：{question}\n\nAI 生成的带有引用编号的完整回答：\n{answer}"
            answers = await jev.system_one(state=state, questions=questions)

            threshold = getattr(jev_cfg, "citation_confidence_threshold", 0.60)
            review_low = getattr(jev_cfg, "citation_review_low", 0.45)
            unsupported = []
            ambiguous = []
            missing: list[int] = []
            scores = {}
            for ref_n in refs:
                key = f"cite_{ref_n}"
                res = answers.get(key) or {}
                # 缺键 ≠ 高置信支持：JEV 没给分就是"未知"，必须升级而不是默认 1.0
                prob = res.get("noul") if isinstance(res, dict) else None
                if prob is None:
                    missing.append(ref_n)
                    continue
                prob = float(prob)
                scores[str(ref_n)] = prob
                if prob < review_low:
                    unsupported.append(ref_n)
                elif prob < threshold:
                    # 灰区：既非明确不支持，也未达高置信支持 -> 整轮升级到既有 LLM 审计
                    ambiguous.append(ref_n)

            if ambiguous or missing:
                logger.warning(
                    "citation verify JEV uncertain -> escalate to LLM",
                    ambiguous=ambiguous,
                    missing=missing,
                    scores=scores,
                )
            else:
                _meta = {
                    "status": "jev_judged",
                    "unsupported": unsupported,
                    "scores": scores,
                    "missing_scores": missing,
                }
                logger.info("citation verify JEV judge", **_meta)

                if not unsupported:
                    return answer, [], _meta

                cited = "、".join(f"[{u}]" for u in unsupported)
                note = (
                    f"\n\n（注：回答中 {cited} 的引用内容未能在当前知识库证据中找到支持，"
                    "相关内容请以官方文件为准。）"
                )
                return answer + note, unsupported, _meta
        except Exception as e:
            logger.warning("JEV citation verify failed, falling back to LLM", error=str(e)[:120])

    # 构造证据映射与 LLM 审计提示词（备用/降级路径）
    evidence_block = "\n".join(
        f"[{i + 1}] {_reference_content(r, i + 1, max_chars=1200)}"
        for i, r in enumerate(references)
    )
    ref_list = ", ".join(str(r) for r in refs)

    system = (
        "你是引用审计助手。回答中的 [n] 表示该论断引用自第 n 条证据。"
        "逐条判断每个 [n] 引用的论断是否确实被对应编号证据支持。"
        '只输出 JSON：{"unsupported": [1, 3]} （列出所有证据不支持的引用编号，全部支持则为空数组）'
    )
    user = (
        f"问题：{question}\n\n回答：{answer}\n\n"
        f"证据列表：\n{evidence_block}\n\n"
        f"回答中出现的引用编号：{ref_list}\n"
        "判断：哪些编号的引用内容在对应证据中找不到支持？（证据提及相似主题但未直接说明的不算支持）"
    )

    try:
        resp = await fallback.chat_completion(
            model=None,
            temperature=0.0,
            max_tokens=256,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        raw = resp.choices[0].message.content or "{}"

        from app.observability import get_active_tracer
        from app.observability.llm_observe import record_generation

        active_tracer = get_active_tracer()
        if active_tracer:
            usage = getattr(resp, "usage", None)
            p_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            c_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            record_generation(
                active_tracer,
                "citation_verify_llm",
                model=str(
                    getattr(resp, "model", None) or getattr(fallback, "model_name", "unknown")
                ),
                input=user,
                output=raw,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
            )

        data = _parse_json(raw)
        unsupported = [int(x) for x in data.get("unsupported", []) if str(x).isdigit()]
        _meta = {"status": "judged", "judge_raw": raw[:200], "unsupported": unsupported}
        logger.info("citation verify judge", **_meta)
    except Exception as e:  # noqa: BLE001
        logger.warning("citation verify failed, skip", error=str(e)[:120])
        # 保守口径：不改正文、不追加尾注，但把"这些引用一条都没核实"单列出来，
        # 否则 citation_accuracy 会把审计失败读成"全部支持"。
        return (
            answer,
            [],
            {
                "status": "error",
                "error": str(e)[:120],
                "unknown_refs": list(refs),
            },
        )

    if not unsupported:
        return answer, [], _meta

    cited = "、".join(f"[{u}]" for u in unsupported)
    note = (
        f"\n\n（注：回答中 {cited} 的引用内容未能在当前知识库证据中找到支持，"
        "相关内容请以官方文件为准。）"
    )
    return answer + note, unsupported, _meta


def _parse_json(raw: str) -> dict[str, Any]:
    """宽容解析 judge JSON 输出（去 markdown 围栏）"""
    import json

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = re.sub(r"^json\s*", "", raw)
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            inner = json.loads(m.group(0))
        except Exception:
            inner = None
        if isinstance(inner, dict):
            return inner
    return {}


def citation_verify_enabled() -> bool:
    return bool(getattr(get_settings().rag, "citation_verify_enabled", True))


def dedupe_references(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """引用条目去重（按 id/title/url 首个非空键保序）。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ref in refs or []:
        key = str(ref.get("id", "")) or str(ref.get("title", "")) or str(ref.get("url", ""))
        if key and key not in seen:
            seen.add(key)
            out.append(ref)
    return out
