"""
离线 RAG 评估 CLI

使用方式：
    uv run python -m scripts.evaluation.cli run          # 运行离线评估
    uv run python -m scripts.evaluation.cli list          # 列出测试集中的问题
"""

from __future__ import annotations

import asyncio
import sys

from scripts.evaluation.datasets.seed_data import SEED_DATASET
from scripts.evaluation.report import generate_console_report
from scripts.evaluation.runner import run_evaluation


def cmd_list() -> None:
    """列出种子测试集中的所有问题"""
    if not SEED_DATASET:
        print("种子数据集为空，请先在 app/evaluation/datasets/seed_data.py 中添加测试数据。")
        return

    print(f"种子测试集共 {len(SEED_DATASET)} 条：")
    print()
    for q in SEED_DATASET:
        cat = q.metadata.get("category", "?")
        diff = q.metadata.get("difficulty", "?")
        print(f"  [{q.id}] ({cat}/{diff}) {q.question[:70]}")


def cmd_run(concurrency: int = 3) -> None:
    """运行离线评估"""
    if not SEED_DATASET:
        print("种子数据集为空，请先在 app/evaluation/datasets/seed_data.py 中添加测试数据。")
        sys.exit(1)

    print(f"开始离线评估：{len(SEED_DATASET)} 条，并发数 {concurrency}")
    print()

    async def _run():
        results = await run_evaluation(SEED_DATASET, concurrency=concurrency)
        report = generate_console_report(results)
        print(report)

    asyncio.run(_run())


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "list":
        cmd_list()
    elif command == "run":
        concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        cmd_run(concurrency)
    else:
        print(f"未知命令: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
