"""
Parent-Block 提升（Parent-Child 块聚合）

设计：检索粒度用 Child 小块保证命中率，回答阶段提升到 Parent 大块保证上下文完整性。
命中 Child 块后，自动替换为其对应的 Parent 块内容。
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import Evidence
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class ParentBlockElevator:
    """
    Parent-Child 块聚合器。
    根据子节点召回情况，向上聚合查找父节点信息，提供更完整的上下文背景。
    """

    async def elevate(
        self,
        evidences: list[Evidence],
        session: AsyncSession | None = None,
    ) -> list[Evidence]:
        if not evidences:
            return evidences

        logger.debug("parent block elevation", count=len(evidences))

        chunk_ids = [ev.chunk_id for ev in evidences if ev.source_type == "document"]
        if not chunk_ids:
            return evidences

        from app.db.models.document import DocumentChunk
        from app.db.session import get_engine

        @contextlib.asynccontextmanager
        async def _ensure_session(s: AsyncSession | None) -> AsyncIterator[AsyncSession]:
            if s is not None:
                yield s
            else:
                logger.warning("parent_block_elevator_no_session", stacklevel=4)
                engine = get_engine()
                async with AsyncSession(engine) as managed:
                    yield managed

        async with _ensure_session(session) as s:
            # 1. 查找这些 chunk 的 parent_chunk_id
            result = await s.execute(
                select(DocumentChunk.id, DocumentChunk.parent_block_id).where(
                    DocumentChunk.id.in_(chunk_ids)
                )
            )
            rows = result.all()

            parent_map = {row.id: row.parent_block_id for row in rows}
            parent_ids_to_fetch = {pid for pid in parent_map.values() if pid}

            parent_contents = {}
            if parent_ids_to_fetch:
                p_result = await s.execute(
                    select(
                        DocumentChunk.id, DocumentChunk.chunk_text, DocumentChunk.section_path
                    ).where(DocumentChunk.id.in_(parent_ids_to_fetch))
                )
                for prow in p_result.all():
                    parent_contents[prow.id] = {"text": prow.chunk_text, "path": prow.section_path}

        # 2. 按 Parent ID 分组聚合
        parent_groups: dict[str, list[Evidence]] = {}
        elevated_evidences = []

        for ev in evidences:
            if ev.source_type != "document":
                elevated_evidences.append(ev)
                continue

            parent_id = parent_map.get(ev.chunk_id)
            if parent_id and parent_id in parent_contents:
                if parent_id not in parent_groups:
                    parent_groups[parent_id] = []
                parent_groups[parent_id].append(ev)
            else:
                elevated_evidences.append(ev)

        # 3. 聚合计算得分与合并文本
        for parent_id, children in parent_groups.items():
            best_child = max(children, key=lambda e: e.score)

            content = parent_contents[parent_id]["text"]
            path = parent_contents[parent_id]["path"]

            final_content = f"【章节路径：{path}】\n{content}" if path else content

            # truncate to parent_evidence_max_chars
            max_chars = settings.rag.parent_evidence_max_chars
            if max_chars > 0 and len(final_content) > max_chars:
                final_content = final_content[:max_chars] + "..."

            # 复用 best_child 作为基座，更新内容但保持原始分数（不重新打分）
            best_child.content = final_content
            # 保留最初始的 RRF 或 BM25 分数（original_score 默认为 0.0，非 None）
            if best_child.original_score == 0.0:
                best_child.original_score = best_child.score

            elevated_evidences.append(best_child)

        return sorted(elevated_evidences, key=lambda e: e.score, reverse=True)
