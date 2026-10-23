"""引用验证器（017 生成侧质量修复：引用纪律的代码级兜底）。

背景（实证）：prompt 引用纪律对顽固幻觉失效——"辞职"问题在证据只有试用期条款时，
模型仍回答"辞职须提前30天书面通知 [1]"（假引用）。LLM 自检在生成后逐引用核对证据，
不支持的引用在回答末尾追加诚实说明（不改写已流式输出的正文）。

成本：每轮 1 次轻量 LLM 调用（仅当回答含引用且证据非空时触发）。
开关：RAG_CITATION_VERIFY_ENABLED（默认开，延迟敏感场景可关）。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog

from app.chat.answer_grounding import audit_grounding, grounding_note
from app.chat.numeric_grounding import caution_note
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


CITATION_INSTRUCTIONS = (
    "回答中标注 [{n}] 的那句话，是否被上面给出的证据 [{n}] "
    "直接支持？证据只是相关但没有直接说到，也算不支持。"
)


def build_citation_question(ref_n: int) -> dict[str, Any]:
    """引用支持判据。生产路径与标定集必须共用它，否则标定的不是线上那套。"""
    return {"type": "noul", "instructions": CITATION_INSTRUCTIONS.format(n=ref_n)}


def build_citation_state(question: str, answer: str, evidence_block: str) -> str:
    """材料进 state、判据进 question（参考实现 feder-cr/jev 的分工）。"""
    return (
        f"用户问题：{question}\n\n"
        f"AI 生成的带有引用编号的完整回答：\n{answer[:_CITATION_ANSWER_CHARS]}\n\n"
        f"证据：\n{evidence_block}"
    )


_CITATION_SHARD_SIZE = 4
_CITATION_EVIDENCE_CHARS = 1200
_CITATION_ANSWER_CHARS = 1500


def _citation_evidence(ref: dict[str, Any] | Any, fallback_id: int, max_chars: int = 400) -> str:
    """取"被引用的那一段"作为判据：优先精确命中的子块，父块上下文只在有空位时追加。

    与 ``_reference_content`` 的区别：后者以父块全文为主（最多 1200 字符），
    放进 noul 判据会挤掉其他引用，且触发服务端左截断后证据反而丢失。
    """
    if not isinstance(ref, dict):
        return str(ref)[:max_chars]
    child = (ref.get("child_chunk_text") or "").strip()
    full = (
        ref.get("content")
        or ref.get("excerpt")
        or ref.get("snippet")
        or ref.get("chunk_text")
        or ""
    ).strip()
    if child:
        if len(child) >= max_chars:
            return child[:max_chars]
        room = max_chars - len(child) - len("【上下文】")
        if room > 80 and full and child not in full:
            return f"{child}\n【上下文】{full[:room]}"
        return child
    if full:
        return full[:max_chars]
    title = (ref.get("title") or "").strip()
    return (title or f"(证据 {fallback_id}，无文本)")[:max_chars]


def _grounding_extra(grounding: Any) -> dict[str, Any]:
    """把"含数值却没有引用"的句子挂到元信息上（只观测，不阻断）。"""
    uncited = getattr(grounding, "uncited_claims", ()) or ()
    if not uncited:
        return {}
    logger.info("uncited_quantitative_claims", count=len(uncited))
    return {"uncited_claims": [c[:80] for c in uncited]}


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
    # 零成本确定性兜底（先于一切模型调用）：悬空引用 / 不存在的文档名 / 不存在的条款号
    # 这三类问题不需要判分模型就能判负，也覆盖"没有 [n] 但编造了一份文档"的失败模式。
    grounding = audit_grounding(answer, references or [])
    if grounding.blocking:
        meta = {
            "status": "deterministic_unsupported",
            "unsupported": list(grounding.unsupported_citations),
            "grounding": grounding.to_meta(),
        }
        logger.warning("answer grounding failed", **grounding.to_meta())
        return answer + grounding_note(grounding), list(grounding.unsupported_citations), meta

    extra = _grounding_extra(grounding)

    # 数字/极性与所引证据对不上时，把结论写进用户可见的尾注：判分模型看不见这类错误
    # （标定：改数字漏 27.5%、翻极性漏 52.5%），而且 LLM 复核可能因为余额/超时而根本跑不起来。
    caution = caution_note(grounding.numeric_mismatches, grounding.polarity_mismatches)
    if caution:
        logger.warning(
            "answer numeric/polarity mismatch",
            numeric=len(grounding.numeric_mismatches),
            polarity=len(grounding.polarity_mismatches),
        )
        answer = answer + caution
        extra = {
            **extra,
            "caution": True,
            "numeric_mismatches": len(grounding.numeric_mismatches),
            "polarity_mismatches": len(grounding.polarity_mismatches),
        }

    refs = extract_citations(answer)
    if not refs:
        return answer, [], {"status": "no_citation", **extra}
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
                i + 1: _citation_evidence(r, i + 1, max_chars=_CITATION_EVIDENCE_CHARS)
                for i, r in enumerate(references)
            }
            # 材料全部进 state（一次读完），判据只描述"要回答什么问题"。
            # 参考实现的做法（feder-cr/jev）：state 放材料、question 放判据；
            # 把证据塞进 instructions 会让判据与证据一起被服务端截断，
            # 而且同样一批证据在每条判据里重复一遍。
            base_question_answer = (question, answer)
            # 分片：每片 <=4 条引用。单请求塞 10+ 条会把判据挤到 4096 token 之外
            # （服务端左截断先砍判断标准），既慢又判不准。
            shards = [
                refs[i : i + _CITATION_SHARD_SIZE]
                for i in range(0, len(refs), _CITATION_SHARD_SIZE)
            ]
            answers: dict[str, Any] = {}

            async def _judge_shard(shard: list[int]) -> dict[str, Any]:
                evidence_block = "\n\n".join(
                    f"[{ref_n}] {evidence_map.get(ref_n, '（该引用编号无对应证据内容）')}"
                    for ref_n in shard
                )
                questions = {f"cite_{ref_n}": build_citation_question(ref_n) for ref_n in shard}
                return await jev.system_one(
                    state=build_citation_state(
                        base_question_answer[0], base_question_answer[1], evidence_block
                    ),
                    questions=questions,
                )

            shard_results = await asyncio.gather(
                *[_judge_shard(shard) for shard in shards], return_exceptions=True
            )
            for shard, result in zip(shards, shard_results, strict=False):
                if isinstance(result, BaseException):
                    # 该片失败 -> 这些引用保持"无分数"，走升级通道，绝不默认通过
                    logger.warning(
                        "citation verify shard failed", refs=shard, error=str(result)[:120]
                    )
                    continue
                answers.update(result or {})

            threshold = getattr(jev_cfg, "citation_confidence_threshold", 0.60)
            # 实测（48 例确定性样本，AUC 0.974）：grounded 最低 0.01、fabricated 最高 0.52，
            # 没有阈值能把两类完全分开。因此 JEV 只做"高置信放行"的筛子：达到阈值就跳过 LLM，
            # 否则一律升级给 LLM 判定 —— 绝不由 1.5B 模型直接给用户扣"引用不支持"的帽子。
            suspicious: list[int] = []
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
                if prob < threshold:
                    suspicious.append(ref_n)

            # 数字落地不通过 -> 无论 JEV 多自信都升级。实测标定：改数字、翻极性、
            # 删条件三族在 0.60 阈值下有 27.5%~52.5% 被高置信放行。
            numeric_refs = {
                int(n)
                for issue in getattr(grounding, "numeric_mismatches", ())
                for n in getattr(issue, "ref_ids", ())
            }
            polarity_refs = {
                int(n)
                for issue in getattr(grounding, "polarity_mismatches", ())
                for n in getattr(issue, "ref_ids", ())
            }
            forced = [n for n in refs if n in numeric_refs | polarity_refs and n not in suspicious]
            if forced:
                logger.info("citation verify numeric mismatch -> escalate", refs=forced)
                suspicious.extend(forced)

            if suspicious or missing:
                logger.warning(
                    "citation verify JEV not confident -> escalate to LLM",
                    suspicious=suspicious,
                    missing=missing,
                    scores=scores,
                )
            else:
                _meta = {
                    "status": "jev_judged",
                    "unsupported": [],
                    "scores": scores,
                    "missing_scores": missing,
                    **extra,
                }
                logger.info("citation verify JEV judge", **_meta)
                return answer, [], _meta
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
        _meta = {
            "status": "judged",
            "judge_raw": raw[:200],
            "unsupported": unsupported,
            **extra,
        }
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
