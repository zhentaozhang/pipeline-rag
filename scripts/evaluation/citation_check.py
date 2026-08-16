"""引用准确率审计：检查回答中 [n] 引用是否被第 n 条证据真正支持。

背景（B 项，015/016 轮）：
- RAG 回答带 [1][2] 引用标注，但从未验证"标了 [1] 的内容是否真的在证据 1 里"
- 引用幻觉（标了不存在的证据）是 RAG 信任杀手
- 本工具：对员工手册数据集逐问请求回答 → LLM-as-judge 逐条判断引用-证据对应

用法：
    uv run python -m scripts.evaluation.citation_check --questions 10
    uv run python -m scripts.evaluation.citation_check --questions 10 --only-miss
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from app.config import get_settings  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.infra.model_fallback import ModelFallbackManager  # noqa: E402

settings = get_settings()

CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citations(answer: str) -> list[int]:
    """提取回答中出现的引用编号（保序去重）"""
    seen: list[int] = []
    for m in CITATION_RE.finditer(answer):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


async def fetch_answer(
    question: str,
    engine: RagRetrievalEngine,
    fallback: ModelFallbackManager,
) -> tuple[str, list[str]]:
    """检索→生成真实回答（与评估 runner 同路径），返回 (answer, final_evidence_contents)"""
    from app.chat.schema import ExecutionMode, ExecutionPlan
    from app.rag.assembly import PromptAssemblyService

    plan = ExecutionPlan(
        original_question=question,
        rewritten_question=question,
        retrieval_question=question,
        mode=ExecutionMode.RETRIEVAL,
    )
    ctx = await engine.retrieve(plan)
    evidences = []
    for se in ctx.sub_question_evidence_list:
        for ev in se.evidences:
            evidences.append(ev.content[:400])

    assembler = PromptAssemblyService()
    prompt_result = assembler.assemble(plan, ctx.sub_question_evidence_list)
    resp = await fallback.chat_completion(
        model=None,
        messages=[
            {"role": "system", "content": prompt_result.system_prompt},
            {"role": "user", "content": prompt_result.user_prompt},
        ],
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )
    answer = (resp.choices[0].message.content or "") if getattr(resp, "choices", None) else ""
    return answer, evidences


async def judge_citations(
    fallback: ModelFallbackManager,
    question: str,
    answer: str,
    evidences: list[str],
) -> tuple[float, list[dict]]:
    """LLM-as-judge：逐条判断每个 [n] 引用是否被证据 n 支持。返回 (accuracy, issues)"""
    refs = extract_citations(answer)
    issues: list[dict] = []
    if not refs:
        return 0.0, [{"ref": None, "reason": "回答无引用标注"}]
    if not evidences:
        return 0.0, [{"ref": None, "reason": "无证据（拒答或检索为空）"}]

    evidence_block = "\n".join(
        f"[{i + 1}] {ev[:300]}" for i, ev in enumerate(evidences)
    )
    ref_list = ", ".join(str(r) for r in refs)
    system = (
        "你是引用审计助手。回答中的 [n] 表示该论断引用自第 n 条证据。"
        "请逐条判断：每个 [n] 引用的论断是否确实被对应编号的证据支持。"
        "只输出 JSON：{\"results\": [{\"ref\": 1, \"supported\": true/false, \"reason\": \"...\"}]}"
    )
    user = (
        f"问题：{question}\n\n回答：{answer}\n\n"
        f"证据列表（前 300 字）：\n{evidence_block}\n\n"
        f"回答中出现的引用编号：{ref_list}\n"
        "对每个编号判断 supported（证据是否支持该引用的论断）。"
    )
    try:
        resp = await fallback.chat_completion(
            model=None,
            temperature=0.0,
            max_tokens=1024,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        results = data.get("results", [])
    except Exception as e:  # noqa: BLE001
        return 0.0, [{"ref": None, "reason": f"judge 解析失败: {e}"}]

    for r in results:
        supported = bool(r.get("supported"))
        if not supported:
            issues.append({"ref": r.get("ref"), "reason": r.get("reason", "")[:120]})
    if not results and refs:
        return 0.0, [{"ref": None, "reason": "judge 未返回逐条结果"}]
    score = sum(1 for r in results if r.get("supported")) / len(results) if results else 0.0
    return score, issues


async def main() -> None:
    parser = argparse.ArgumentParser(description="引用准确率审计")
    parser.add_argument("--questions", type=int, default=10)
    parser.add_argument("--only-miss", action="store_true", help="只显示未命中项")
    parser.add_argument("--json-report", type=str, default="/tmp/citation-report.json")
    args = parser.parse_args()

    await init_db()
    from scripts.evaluation.datasets import load_dataset

    ds = load_dataset()
    items = ds[: args.questions]

    from app.common.llm_client import get_chat_client
    from app.rag.engine import RagRetrievalEngine

    engine = RagRetrievalEngine()
    fallback = ModelFallbackManager(client=get_chat_client())
    print(f"引用准确率审计（{len(items)} 问，LLM-as-judge）\n" + "-" * 60)
    total_score, total_issues, total_refs = 0.0, 0, 0
    rows = []
    for i, item in enumerate(items, 1):
        answer, evidences = await fetch_answer(item.question, engine, fallback)
        score, issues = await judge_citations(fallback, item.question, answer, evidences)
        refs = extract_citations(answer)
        total_score += score
        total_refs += len(refs)
        total_issues += len(issues)
        status = "✅" if score >= 1.0 else ("⚠️" if score >= 0.5 else "❌")
        print(
            f"{status} Q{i} 引用[{len(refs)}] 准确率={score:.2f} "
            f"{item.question[:24]}"
        )
        rows.append(
            {"question": item.question, "answer_len": len(answer), "refs": refs,
             "evidence_count": len(evidences), "accuracy": score, "issues": issues}
        )
        if issues and not args.only_miss:
            for iss in issues[:3]:
                print(f"     ✗ [{iss.get('ref')}] {iss.get('reason', '')[:80]}")

    print("-" * 60)
    avg = total_score / len(items) if items else 0.0
    print(f"平均引用准确率: {avg:.3f} | 总引用 {total_refs} | 问题引用 {total_issues}")
    with open(args.json_report, "w", encoding="utf-8") as f:
        json.dump({"avg_citation_accuracy": avg, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"报告: {args.json_report}")


if __name__ == "__main__":
    asyncio.run(main())
