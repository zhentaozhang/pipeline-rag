"""关键词通道离线诊断（零成本 · 本地 ES）。

对数据集中每题单独运行关键词通道，评估其对标注真值片段的召回质量：
  - recall@k / hit@k（k 可配，默认 5/10/20/50）
  - MRR（首个覆盖到任一标注片段的排名）
  - 按 5 大企业场景分组

全程**不调用** LLM / Embedding / Rerank，仅访问本地 Elasticsearch，可零成本反复运行，
用于在修改关键词侧（analyzer/msm/boost 等）后快速判断"是否正向"。

用法：
    python -m scripts.evaluation.analyze_keyword
    python -m scripts.evaluation.analyze_keyword --k 5,10,20,50
"""

from __future__ import annotations

import argparse
import asyncio

from app.chat.schema import SubQuestion
from app.rag.channels.keyword import KeywordRetrievalChannel
from scripts.evaluation.datasets import load_dataset
from scripts.evaluation.metrics import _char_bigrams

CATEGORIES: dict[str, tuple[int, int]] = {
    "Cat1 数值与限制": (1, 20),
    "Cat2 分支与前置条件": (21, 38),
    "Cat3 多跳复杂推理": (39, 55),
    "Cat4 时效版本冲突": (56, 70),
    "Cat5 反向与安全拒答": (71, 85),
}


def _covers(relevant: str, texts: list[str]) -> bool:
    """与 scripts.evaluation.metrics.compute_recall_at_k 同口径的覆盖判定。"""
    rb = _char_bigrams(str(relevant).strip())
    if not rb:
        return any(str(relevant).lower() in t.lower() for t in texts)
    return any(len(rb & _char_bigrams(t)) / len(rb) >= 0.5 for t in texts)


def _cat_of(question_id: str) -> str:
    try:
        n = int(question_id.replace("emp", ""))
    except ValueError:
        return "其他"
    for name, (lo, hi) in CATEGORIES.items():
        if lo <= n <= hi:
            return name
    return "其他"


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


async def _run(ks: list[int]) -> None:
    from app.infra.es import close_es, init_es

    await init_es()
    channel = KeywordRetrievalChannel()
    dataset = load_dataset()
    rows: list[dict] = []
    try:
        for q in dataset:
            sub = SubQuestion(index=0, text=q.question, original=q.question)
            try:
                evidences = await channel.retrieve(sub)
            except Exception:
                evidences = []
            texts = [e.content for e in evidences if e.content]
            rels = q.relevant_contexts or []
            rec = {
                k: (sum(1 for r in rels if _covers(r, texts[:k])) / len(rels) if rels else 0.0)
                for k in ks
            }
            mrr = 0.0
            for rank, t in enumerate(texts, start=1):
                if any(_covers(r, [t]) for r in rels):
                    mrr = 1.0 / rank
                    break
            rows.append(
                {"id": q.id, "cat": _cat_of(q.id), "n_ev": len(texts), "rec": rec, "mrr": mrr}
            )
    finally:
        await close_es()

    header = f"{'category':<22}{'n':>4}" + "".join(f"{'R@' + str(k):>9}" for k in ks)
    header += f"{'MRR':>9}{'avg#ev':>9}"
    print(header)
    print("-" * len(header))
    for cat in list(CATEGORIES) + ["其他"]:
        sub = [r for r in rows if r["cat"] == cat]
        if not sub:
            continue
        line = f"{cat:<22}{len(sub):>4}"
        line += "".join(f"{_mean([r['rec'][k] for r in sub]):>9.3f}" for k in ks)
        line += f"{_mean([r['mrr'] for r in sub]):>9.3f}{_mean([r['n_ev'] for r in sub]):>9.1f}"
        print(line)
    print("-" * len(header))
    line = f"{'ALL':<22}{len(rows):>4}"
    line += "".join(f"{_mean([r['rec'][k] for r in rows]):>9.3f}" for k in ks)
    line += f"{_mean([r['mrr'] for r in rows]):>9.3f}{_mean([r['n_ev'] for r in rows]):>9.1f}"
    print(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="关键词通道离线诊断（零成本·本地 ES）")
    parser.add_argument("--k", type=str, default="5,10,20,50", help="逗号分隔的 k 值")
    cli_args = parser.parse_args()
    k_values = [int(x) for x in cli_args.k.split(",") if x.strip()]
    asyncio.run(_run(k_values))
