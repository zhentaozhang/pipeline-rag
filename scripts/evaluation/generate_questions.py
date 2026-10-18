"""从语料自动出题（Task 4）：把评测集从 85 题扩到数百题，提高统计分辨率。

没有人工标注，出题也交给 LLM，但必须守住"可验证"：每道题都锚定**一个具体 chunk**，
并给出该 chunk 的抽取式答案；再用第二个 prompt 做**校验**（题目能否只凭该 chunk 回答、
答案是否与 chunk 一致），不过关的丢弃。这样 gold 是 chunk_id，天然可机器核对。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_WS_RE = re.compile(r"\s+")

_GEN_SYSTEM = """你是企业 HR/行政制度问答的数据标注员。给定一段制度原文，你要出 1 道题。
硬性要求：
1. 题目只能靠这段原文回答，不能依赖原文以外的常识或其他条款；
2. 题目要像员工真实会问的问题，口语化，不要提"根据上文""这段文字"；
3. 答案必须能从原文直接摘出（≤80 字），不允许推算、不允许补全原文没有的数字；
4. 若原文是目录、页眉、无实质内容的片段，返回 {"skip": true}。
只输出 JSON：{"question": "...", "answer": "...", "skip": false}"""

_VERIFY_SYSTEM = """你是数据质检员。给定一段制度原文和一道候选题（含答案），判断：
1. 这道题能否**只凭该原文**回答？
2. 给出的答案与原文是否一致（数字、期限、比例必须完全一致）？
两项都满足才通过。只输出 JSON：{"pass": true/false, "reason": "..."}"""


def _norm(text: str) -> str:
    return _WS_RE.sub("", text or "").lower()


def question_key(question: str) -> str:
    """题目去重键：忽略空白与大小写。"""
    return _norm(question)


def parse_generation(text: str) -> dict[str, Any] | None:
    """解析出题响应；skip 或格式非法返回 None。"""
    from app.observability.metrics.base import parse_json_safe

    data = parse_json_safe(text, default={})
    if not isinstance(data, dict) or data.get("skip"):
        return None
    question = str(data.get("question") or "").strip()
    answer = str(data.get("answer") or "").strip()
    if not question or not answer:
        return None
    return {"question": question, "answer": answer}


def parse_verification(text: str) -> bool:
    """解析质检响应；解析不出来按不通过处理（宁可少题，不可脏题）。"""
    from app.observability.metrics.base import parse_json_safe

    data = parse_json_safe(text, default={})
    if isinstance(data, dict):
        return bool(data.get("pass"))
    return False


def question_id(chunk_id: str, idx: int) -> str:
    """稳定可复现的题号（同 chunk 同序号恒等）。"""
    digest = hashlib.sha1(f"{chunk_id}:{idx}".encode()).hexdigest()[:6]
    return f"gen{chunk_id}_{idx}_{digest}"


def build_generation_messages(chunk_text: str, *, section_path: str = "") -> list[dict[str, str]]:
    body = chunk_text.strip()
    if section_path:
        body = f"[章节] {section_path}\n{body}"
    return [
        {"role": "system", "content": _GEN_SYSTEM},
        {"role": "user", "content": body},
    ]


def build_verification_messages(
    chunk_text: str, question: str, answer: str, *, section_path: str = ""
) -> list[dict[str, str]]:
    body = chunk_text.strip()
    if section_path:
        body = f"[章节] {section_path}\n{body}"
    return [
        {"role": "system", "content": _VERIFY_SYSTEM},
        {
            "role": "user",
            "content": f"{body}\n\n[候选题] {question}\n[候选答案] {answer}",
        },
    ]


async def _chat(client: Any, messages: list[dict[str, str]], *, model: str | None) -> str:
    from app.config import get_settings

    resp = await client.chat.completions.create(
        model=model or get_settings().llm.model,
        messages=messages,
        temperature=0.3,
        max_tokens=512,
    )
    return resp.choices[0].message.content or ""


async def build_generated_dataset(
    chunks: list[dict[str, Any]],
    *,
    per_chunk: int = 1,
    concurrency: int = 6,
    verify: bool = True,
    model: str | None = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """对每个 chunk 出题（可选质检），返回题目列表。"""
    from app.common.llm_client import get_chat_client

    client = get_chat_client()
    targets = chunks[:limit] if limit > 0 else chunks
    semaphore = asyncio.Semaphore(concurrency)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    async def _one(chunk: dict[str, Any]) -> list[dict[str, Any]]:
        chunk_id = str(chunk["id"])
        text = (chunk.get("chunk_text") or "").strip()
        if len(text) < 60:
            return []
        produced: list[dict[str, Any]] = []
        for idx in range(per_chunk):
            async with semaphore:
                try:
                    raw = await _chat(
                        client,
                        build_generation_messages(
                            text, section_path=chunk.get("section_path") or ""
                        ),
                        model=model,
                    )
                except Exception as exc:  # noqa: BLE001 — 单 chunk 失败不影响整体
                    logger.warning("generate failed", chunk_id=chunk_id, error=str(exc)[:120])
                    continue
            parsed = parse_generation(raw)
            if parsed is None:
                continue
            key = question_key(parsed["question"])
            if key in seen:
                continue
            seen.add(key)
            produced.append(
                {
                    "id": question_id(chunk_id, idx),
                    "question": parsed["question"],
                    "ground_truth_answer": parsed["answer"],
                    "relevant_chunk_ids": [chunk_id],
                    "relevant_contexts": [parsed["answer"]],
                    "category": "generated",
                    "source_document_id": chunk.get("document_id"),
                }
            )
        return produced

    for result in await asyncio.gather(*[_one(c) for c in targets]):
        out.extend(result)

    if verify and out:
        by_id = {str(c["id"]): c for c in targets}
        semaphore_v = asyncio.Semaphore(concurrency)

        async def _verify(item: dict[str, Any]) -> bool:
            chunk = by_id.get(str(item["relevant_chunk_ids"][0]))
            if chunk is None:
                return False
            async with semaphore_v:
                try:
                    raw = await _chat(
                        client,
                        build_verification_messages(
                            (chunk.get("chunk_text") or "").strip(),
                            item["question"],
                            item["ground_truth_answer"],
                            section_path=chunk.get("section_path") or "",
                        ),
                        model=model,
                    )
                except Exception as exc:  # noqa: BLE001 — 质检失败按不通过
                    logger.warning("verify failed", qid=item["id"], error=str(exc)[:120])
                    return False
            return parse_verification(raw)

        verdicts = await asyncio.gather(*[_verify(item) for item in out])
        out = [item for item, ok in zip(out, verdicts, strict=True) if ok]

    logger.info("generated dataset", chunks=len(targets), questions=len(out))
    return out


async def _load_chunks() -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models.document import DocumentChunk
    from app.db.session import close_db, get_session_factory, init_db

    await init_db()
    factory = get_session_factory()
    assert factory is not None
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.chunk_text,
                    DocumentChunk.section_path,
                    DocumentChunk.document_id,
                )
            )
        ).all()
    await close_db()
    return [
        {
            "id": row[0],
            "chunk_text": row[1] or "",
            "section_path": row[2] or "",
            "document_id": row[3],
        }
        for row in rows
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="从语料自动生成评测题（LLM 出题 + LLM 质检）")
    parser.add_argument("--out", default="reports/generated_questions.json")
    parser.add_argument("--per-chunk", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)

    async def _run() -> list[dict[str, Any]]:
        chunks = await _load_chunks()
        return await build_generated_dataset(
            chunks,
            per_chunk=args.per_chunk,
            concurrency=args.concurrency,
            verify=not args.no_verify,
            limit=args.limit,
        )

    items = asyncio.run(_run())
    Path(args.out).write_text(
        json.dumps(
            {
                "meta": {
                    "count": len(items),
                    "per_chunk": args.per_chunk,
                    "verified": not args.no_verify,
                },
                "questions": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("written", path=args.out, count=len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
