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


def _reference_content(ref: dict[str, Any] | Any, fallback_id: int) -> str:
    """从 reference 条目提取证据文本（按 id 或 title）"""
    if isinstance(ref, dict):
        return (
            ref.get("content")
            or ref.get("excerpt")
            or ref.get("title")
            or ref.get("chunk_text")
            or f"(证据 {fallback_id}，无文本)"
        )
    return str(ref)


async def verify_citations(
    fallback: Any,
    answer: str,
    references: list[dict[str, Any] | Any],
    question: str = "",
) -> tuple[str, list[int]]:
    """验证回答中每个 [n] 引用是否被对应证据支持。

    返回 (修正后 answer, 不支持/无法核实的引用编号列表)。
    仅追加说明，不改写正文（正文已流式发出）。
    """
    refs = extract_citations(answer)
    if not refs:
        return answer, [], {"status": "no_citation"}
    if not references:
        note = "\n\n（注：回答中标注的引用未能从当前知识库证据核实，请以官方文件为准。）"
        return answer + note, refs, {"status": "no_evidence"}

    # 构造证据映射：reference 列表按顺序对应 [1][2]...
    evidence_block = "\n".join(
        f"[{i + 1}] {_reference_content(r, i + 1)[:280]}" for i, r in enumerate(references)
    )
    ref_list = ", ".join(str(r) for r in refs)

    system = (
        "你是引用审计助手。回答中的 [n] 表示该论断引用自第 n 条证据。"
        "逐条判断每个 [n] 引用的论断是否确实被对应编号证据支持。"
        "只输出 JSON：{\"unsupported\": [1, 3]} （列出所有证据不支持的引用编号，全部支持则为空数组）"
    )
    user = (
        f"问题：{question}\n\n回答：{answer}\n\n"
        f"证据列表（前 280 字）：\n{evidence_block}\n\n"
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
        data = _parse_json(raw)
        unsupported = [int(x) for x in data.get("unsupported", []) if str(x).isdigit()]
        _meta = {"status": "judged", "judge_raw": raw[:200], "unsupported": unsupported}
        logger.info("citation verify judge", **_meta)
    except Exception as e:  # noqa: BLE001
        logger.warning("citation verify failed, skip", error=str(e)[:120])
        return answer, [], {"status": "error", "error": str(e)[:120]}

    if not unsupported:
        return answer, [], _meta

    cited = "、".join(f"[{u}]" for u in unsupported)
    note = (
        f"\n\n（注：回答中 {cited} 的引用内容未能在当前知识库证据中找到支持，"
        "相关内容请以官方文件为准。）"
    )
    return answer + note, unsupported, _meta


def _parse_json(raw: str) -> dict:
    """宽容解析 judge JSON 输出（去 markdown 围栏）"""
    import json

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = re.sub(r"^json\s*", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def citation_verify_enabled() -> bool:
    return bool(getattr(get_settings().rag, "citation_verify_enabled", True))
