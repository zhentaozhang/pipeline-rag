"""判据标定执行器：把构造好的样本喂给**生产用的同一套 prompt**，收集置信度并汇总。

用法（需 JEV 服务在线，本机免费）::

    env -u NO_PROXY -u no_proxy .venv/bin/python -m scripts.evaluation.calibration_runner \
        --per-kind 40 --concurrency 4 --out reports/calibration_citation.json

`--dry-run` 只构造样本、打印分布，不调任何模型（可离线跑）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Judge = Callable[[Any], Awaitable[float | None]]


def case_to_state(case: Any) -> str:
    """把一条标定样本拼成与生产一致的 state：问题 + 带 [1] 的回答 + 证据。"""
    from app.chat.citation_verifier import build_citation_state

    return build_citation_state(case.question, f"{case.answer} [1]", f"[1] {case.evidence}")


def _summarize_rows(rows: list[dict]) -> dict:
    from scripts.evaluation.calibration_metrics import summarize

    pairs = [(r["prob"], r["label"]) for r in rows]
    summary = summarize(pairs)
    if pairs:
        from scripts.evaluation.calibration_metrics import choose_threshold

        summary["suggested_threshold"] = choose_threshold(pairs, max_false_pass=0.05)
    else:
        summary["suggested_threshold"] = None
    return summary


async def evaluate_cases(cases: list[Any], judge: Judge, *, concurrency: int = 4) -> dict[str, Any]:
    """并发跑判据，按 kind 分组汇总。判据失败/无分数记入 errors，绝不当 0 分计入。"""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    rows: list[dict] = []
    errors: list[str] = []

    async def run_one(case: Any) -> None:
        async with semaphore:
            try:
                prob = await judge(case)
            except Exception as exc:  # 服务故障不能污染标定结论
                logger.warning(
                    "calibration judge failed case=%s err=%s", case.case_id, str(exc)[:120]
                )
                errors.append(case.case_id)
                return
        if prob is None:
            errors.append(case.case_id)
            return
        rows.append(
            {
                "case_id": case.case_id,
                "kind": case.kind,
                "prob": float(prob),
                "label": int(case.expected_supported),
            }
        )

    await asyncio.gather(*[run_one(case) for case in cases])

    by_kind: dict[str, dict] = {}
    for kind in sorted({r["kind"] for r in rows}):
        by_kind[kind] = _summarize_rows([r for r in rows if r["kind"] == kind])
    return {
        "overall": _summarize_rows(rows),
        "by_kind": by_kind,
        "rows": rows,
        "errors": errors,
    }


def _print_report(report: dict) -> None:
    def fmt(value: Any, digits: int = 3) -> str:
        if value is None:
            return "  N/A"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    overall = report["overall"]
    print("\n=== 判据标定（citation_support）===")
    print(
        f"样本 {overall['n']}（正 {overall['positives']} / 负 {overall['negatives']}）  失败 {len(report['errors'])}"
    )
    print(
        f"AUC {fmt(overall['auc'])}  ECE {fmt(overall['ece'])}  "
        f"可用={'是' if overall['usable'] else '否'}"
    )
    picked = overall.get("suggested_threshold")
    if picked:
        print(
            f"建议阈值 {picked['threshold']:.2f}（放行 {picked['true_pass_rate']:.1%} 正样本，"
            f"误放 {picked['false_pass_rate']:.1%} 负样本，精确率 {picked['precision']:.1%}）"
        )
    print("\n分类型：")
    for kind, s in report["by_kind"].items():
        print(
            f"  {kind:16s} n={s['n']:<4d} AUC {fmt(s['auc'])}  ECE {fmt(s['ece'])}  "
            f"正/负均值隐含 base={fmt(s['base_rate'])}"
        )


async def _load_chunks(limit: int = 0) -> list[dict]:
    from sqlalchemy import select

    from app.db.models.document import Document, DocumentChunk
    from app.db.session import get_session_factory, init_db

    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_text,
                DocumentChunk.section_path,
                Document.document_name,
            )
            .join(Document, Document.id == DocumentChunk.document_id, isouter=True)
            .where(DocumentChunk.chunk_text.is_not(None))
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()
    return [
        {
            "chunk_id": str(r[0]),
            "document_id": r[1],
            "chunk_text": r[2] or "",
            "section_path": r[3] or "",
            "document_name": r[4] or "",
        }
        for r in rows
    ]


def _jev_judge_factory() -> Judge:
    from app.chat.citation_verifier import build_citation_question
    from app.infra.jev_client import get_jev_client

    async def judge(case: Any) -> float | None:
        client = get_jev_client()
        answers = await client.system_one(
            state=case_to_state(case), questions={"cite_1": build_citation_question(1)}
        )
        if not isinstance(answers, dict):
            return None
        payload = answers.get("cite_1")
        if not isinstance(payload, dict):
            return None
        prob = payload.get("noul")
        return None if prob is None else float(prob)

    return judge


async def _amain(args: argparse.Namespace) -> int:
    from app.db.session import close_db
    from scripts.evaluation.calibration_cases import build_cases, case_counts

    try:
        chunks = await _load_chunks(args.limit_chunks)
    finally:
        await close_db()
    if not chunks:
        print("没有读到 chunk，先确认数据库与 tenant", file=sys.stderr)
        return 1
    cases = build_cases(chunks, per_kind=args.per_kind, seed=args.seed)
    distribution = case_counts(cases)
    print(f"语料 chunk {len(chunks)} 条 → 标定样本 {len(cases)} 条：{distribution}")
    if args.dry_run:
        return 0

    report = await evaluate_cases(cases, _jev_judge_factory(), concurrency=args.concurrency)
    _print_report(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="判据标定（构造式标签，无需人工标注）")
    parser.add_argument("--per-kind", type=int, default=40, help="每类样本目标条数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit-chunks", type=int, default=0, help="只取前 N 个 chunk（调试用）")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default="reports/calibration_citation.json")
    parser.add_argument("--dry-run", action="store_true", help="只构造样本，不调用模型")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
