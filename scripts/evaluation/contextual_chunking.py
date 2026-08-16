"""Contextual Chunking（Anthropic 2024.9 方法）落地工具。

对每个 chunk：LLM 基于「所属章节 + 前后 chunk 语境」生成 1-2 句上下文描述，
附加到 chunk 后重新 embedding（提升跨章节/同义表述的召回）。

用法：
    # 1. 备份旧向量（可回滚）
    uv run python -m scripts.evaluation.contextual_chunking --backup
    # 2. dry-run：生成上下文描述并预览（不写入）
    uv run python -m scripts.evaluation.contextual_chunking --dry-run --questions 8
    # 3. 应用：更新 PG embedding
    uv run python -m scripts.evaluation.contextual_chunking --apply
    # 4. 回滚
    uv run python -m scripts.evaluation.contextual_chunking --restore
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import structlog  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.infra.pg import execute, fetch  # noqa: E402

logger = structlog.get_logger(__name__)
settings = get_settings()

BACKUP_PATH = Path("/tmp/contextual-chunk-backup.json")
TABLE = "pipeline_rag_document_embedding"


def _env_llm() -> tuple[str, str, str]:
    """返回 (api_key, base_url, model)"""
    return (
        settings.llm.api_key,
        settings.llm.base_url,
        settings.llm.model or "deepseek-v4-flash",
    )


async def load_chunks() -> list[dict]:
    """按文档+序号加载全部 chunk（含前后文）"""
    rows = await fetch(
        f"""
        SELECT id, document_id, chunk_no, section_path, chunk_text
        FROM {TABLE}
        ORDER BY document_id, chunk_no
        """
    )
    return rows


def build_context_window(chunks: list[dict], i: int) -> str:
    """Anthropic 式上下文窗口：所属章节 + 前后各一个 chunk 的语境"""
    c = chunks[i]
    prev_text = chunks[i - 1]["chunk_text"][:200] if i > 0 else ""
    next_text = chunks[i + 1]["chunk_text"][:200] if i < len(chunks) - 1 else ""
    parts = []
    if c.get("section_path"):
        parts.append(f"文档章节：{c['section_path']}")
    if prev_text:
        parts.append(f"前文语境：{prev_text}")
    if next_text:
        parts.append(f"后文语境：{next_text}")
    return "\n".join(parts)


async def generate_contextual_descriptions(chunks: list[dict]) -> list[str]:
    """为每个 chunk 生成 1-2 句上下文描述（LLM）"""
    from openai import AsyncOpenAI

    api_key, base_url, model = _env_llm()
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=120)
    system = (
        "你是一个文档索引助手。给定一个知识库 chunk（含章节与前后文语境），"
        "用 1-2 句中文描述『这个 chunk 在文档中讲述什么内容/主题』，"
        "作为检索上下文补充。要求：概括主题与关键实体，不要重复 chunk 原文细节。"
    )
    descriptions: list[str] = []
    # 分批并发（每批 8 个），控制速率
    for start in range(0, len(chunks), 8):
        batch = chunks[start : start + 8]
        tasks = []
        for i, c in enumerate(batch, start):
            ctx_window = build_context_window(chunks, i)
            user = (
                f"{ctx_window}\n\n"
                f"以下是 chunk 内容（{c['chunk_text'][:800]}）\n\n"
                "请用 1-2 句描述该 chunk 的主题语境。"
            )
            tasks.append(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    max_tokens=120,
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                descriptions.append("")
                logger.warning("contextual generation failed", error=str(r)[:120])
            else:
                descriptions.append((r.choices[0].message.content or "").strip())
        logger.info("contextual batch done", batch=start // 8)
    return descriptions


async def backup() -> None:
    rows = await load_chunks()
    data = [{"id": r["id"], "embedding": None} for r in rows]
    # 读现有向量（文本格式）
    all_rows = await fetch(f"SELECT id, embedding::text AS emb FROM {TABLE}")
    by_id = {r["id"]: r["emb"] for r in all_rows}
    for item in data:
        item["embedding"] = by_id.get(item["id"])
    BACKUP_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"备份 {len(data)} 条向量 → {BACKUP_PATH}")


async def restore() -> None:
    if not BACKUP_PATH.exists():
        print("无备份文件，跳过回滚")
        return
    data = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    for item in data:
        await execute(
            f"UPDATE {TABLE} SET embedding = $1::vector WHERE id = $2",
            item["embedding"],
            item["id"],
        )
    print(f"已回滚 {len(data)} 条")


async def apply(chunks: list[dict], descriptions: list[str]) -> None:
    """附加描述并重新 embedding，更新 PG"""
    from app.infra.embedding import get_embedding_provider

    provider = get_embedding_provider()
    enriched = []
    for c, desc in zip(chunks, descriptions):
        text = f"{desc}\n\n{c['chunk_text']}" if desc else c["chunk_text"]
        enriched.append(text)
    vectors = await provider.embed_batch(enriched)
    for c, vec in zip(chunks, vectors):
        await execute(
            f"UPDATE {TABLE} SET embedding = $1::vector WHERE id = $2",
            f"[{','.join(str(f) for f in vec)}]",
            c["id"],
        )
    print(f"已应用 Contextual Chunking：{len(chunks)} 条（{sum(1 for d in descriptions if d)} 条带描述）")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", action="store_true", help="备份旧向量")
    parser.add_argument("--restore", action="store_true", help="回滚旧向量")
    parser.add_argument("--apply", action="store_true", help="应用（生成描述+重embedding+更新）")
    parser.add_argument("--dry-run", action="store_true", help="预览描述（不写入）")
    parser.add_argument("--questions", type=int, default=8, help="dry-run 预览条数")
    args = parser.parse_args()

    await init_db()

    if args.backup:
        await backup()
        return
    if args.restore:
        await restore()
        return

    chunks = await load_chunks()
    print(f"加载 {len(chunks)} 条 chunk")
    descriptions = await generate_contextual_descriptions(chunks)

    if args.dry_run:
        for i, c in enumerate(chunks[: args.questions]):
            print(f"--- chunk {c['id']} ({c.get('section_path') or '无章节'})")
            print(f"描述: {descriptions[i][:100]}")
        return

    if args.apply:
        await apply(chunks, descriptions)


if __name__ == "__main__":
    asyncio.run(main())
