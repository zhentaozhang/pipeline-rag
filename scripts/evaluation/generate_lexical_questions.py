"""编号类题目候选生成器（只生成候选，人工终审后写入 lexical_dataset.py）。

为什么脚本化：gold 必须是确定性的（包含该条款的 chunk_id），LLM 生成题目无法保证
"答案确实在这段原文里"；而且条款号在语料里跨文档重号，gold 可能是**多个 chunk**。

注意：生成出来的题干是"泛问"（"讲了什么"），不能直接进题库——终审规则要求
答案能被唯一确定（数字/比例/名单），所以本脚本只负责把"候选池"缩到人可读的规模。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

_CLAUSE_TITLE_RE = re.compile(r"^第\s*(\d{1,3})\s*条\s*(.*)$")
_SUB_BOLD_RE = re.compile(r"\*\*(\d{1,2}\.\d{1,2})")
_GRADE_RE = re.compile(r"(?<![A-Za-z0-9])(M[1-9]\+?|P[1-9](?:-\d+)?)(?![A-Za-z0-9])")
_CITY_RE = re.compile(r"([A-D])\s*类城市")


def build_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows: [{chunk_id, parent_block_id, document_name, section_path, chunk_text}]"""
    by_clause: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        path = (row.get("section_path") or "").strip()
        match = _CLAUSE_TITLE_RE.match(path)
        if not match:
            continue
        by_clause.setdefault(match.group(1), []).append(row)

    candidates: list[dict[str, Any]] = []
    for clause, items in sorted(by_clause.items(), key=lambda kv: int(kv[0])):
        if len({i.get("document_name") for i in items}) >= 2:
            candidates.append(
                {
                    "subtype": "clause_ambiguous",
                    "clause": clause,
                    "question": f"第{clause}条规定的内容在几份制度里都出现过，分别讲了什么？",
                    "gold_chunk_ids": [i["chunk_id"] for i in items],
                    "docs": [i["document_name"] for i in items],
                }
            )
        for item in items:
            text = item.get("chunk_text") or ""
            sub = _SUB_BOLD_RE.search(text)
            if sub:
                candidates.append(
                    {
                        "subtype": "clause_sub",
                        "clause": clause,
                        "subclause": sub.group(1),
                        "question": f"《{item['document_name']}》第{clause}条 {sub.group(1)} 规定了什么？",
                        "gold_chunk_ids": [item["chunk_id"]],
                        "docs": [item["document_name"]],
                    }
                )
            grades = _GRADE_RE.findall(text)
            cities = _CITY_RE.findall(text)
            if grades and cities:
                candidates.append(
                    {
                        "subtype": "clause_grade",
                        "clause": clause,
                        "question": (
                            f"第{clause}条里，{grades[0]} 在 {cities[0]} 类城市的标准是多少？"
                        ),
                        "gold_chunk_ids": [item["chunk_id"]],
                        "docs": [item["document_name"]],
                    }
                )
            candidates.append(
                {
                    "subtype": "clause_doc",
                    "clause": clause,
                    "question": f"《{item['document_name']}》第{clause}条规定了什么？",
                    "gold_chunk_ids": [item["chunk_id"]],
                    "docs": [item["document_name"]],
                }
            )
    return candidates


async def _load_rows() -> list[dict[str, Any]]:
    from app.infra.pg import close_pg, fetch, init_pg

    await init_pg()
    try:
        rows = await fetch(
            """SELECT id AS chunk_id, parent_block_id,
                      metadata_json->>'documentName' AS document_name,
                      section_path, chunk_text
               FROM pipeline_rag_document_embedding
               WHERE section_path LIKE '%第%条%'"""
        )
    finally:
        await close_pg()
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/lexical_candidates.json")
    parser.add_argument("--per-subtype", type=int, default=0, help="0=全量")
    args = parser.parse_args(argv)
    rows = asyncio.run(_load_rows())
    candidates = build_candidates(rows)
    if args.per_subtype:
        picked: dict[str, int] = {}
        kept = []
        for cand in candidates:
            n = picked.get(cand["subtype"], 0)
            if n < args.per_subtype:
                kept.append(cand)
                picked[cand["subtype"]] = n + 1
        candidates = kept
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"candidates": candidates}, fh, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "count": len(candidates),
                "by_subtype": {
                    s: sum(1 for c in candidates if c["subtype"] == s)
                    for s in {c["subtype"] for c in candidates}
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
