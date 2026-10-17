"""
Parent-Block 提升（Parent-Child 块聚合）

设计：检索粒度用 Child 小块保证命中率，回答阶段提升到 Parent 大块保证上下文完整性。
命中 Child 块后，自动替换为其对应的 Parent 块内容。
"""

from __future__ import annotations

import contextlib
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import Evidence
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class _LRUCache:
    """线程安全的内存级 LRU 缓存"""

    def __init__(self, maxsize: int = 2048) -> None:
        self._maxsize = maxsize
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_CHUNK_PARENT_CACHE = _LRUCache(maxsize=4096)
_PARENT_CONTENT_CACHE = _LRUCache(maxsize=2048)


def clear_parent_block_cache() -> None:
    """清理 ParentBlock 内存缓存（文档重新索引或删除时调用）"""
    _CHUNK_PARENT_CACHE.clear()
    _PARENT_CONTENT_CACHE.clear()


class ParentBlockElevator:
    """
    Parent-Child 块聚合器。
    根据子节点召回情况，向上聚合查找父节点信息，提供更完整的上下文背景。
    支持内存级双重 LRU 缓存，削减 80%+ 的重复查库 I/O。
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

        from app.db.models.document import DocumentChunk, DocumentParentBlock
        from app.db.session import get_engine, get_session_factory

        @contextlib.asynccontextmanager
        async def _ensure_session(s: AsyncSession | None) -> AsyncIterator[AsyncSession]:
            if s is not None:
                yield s
            else:
                logger.debug("parent_block_elevator_using_managed_session", stacklevel=4)
                factory = get_session_factory()
                if factory is not None:
                    async with factory() as managed:
                        yield managed
                else:
                    engine = get_engine()
                    async with AsyncSession(engine, expire_on_commit=False) as managed:
                        yield managed

        # 1. 查找这些 chunk 的 parent_chunk_id (优先查局部 LRU 缓存)
        parent_map: dict[str, str | None] = {}
        missing_chunk_ids: list[Any] = []
        for cid in chunk_ids:
            cid_str = str(cid)
            cached_pid = _CHUNK_PARENT_CACHE.get(cid_str)
            if cached_pid is not None:
                parent_map[cid_str] = cached_pid if cached_pid != "__none__" else None
            else:
                missing_chunk_ids.append(cid)

        # 2. 对未命中的 chunk_id 批量查库并回填
        if missing_chunk_ids:
            from app.common.utils import stable_id_to_int

            cid_to_query_map = {stable_id_to_int(cid): str(cid) for cid in missing_chunk_ids}
            query_cids = list(cid_to_query_map.keys())
            async with _ensure_session(session) as s:
                result = await s.execute(
                    select(DocumentChunk.id, DocumentChunk.parent_block_id).where(
                        DocumentChunk.id.in_(query_cids)
                    )
                )
                found_cids = set()
                for row in result.all():
                    orig_cid = cid_to_query_map.get(row.id, str(row.id))
                    cid_str = str(row.id)
                    pid_str = str(row.parent_block_id) if row.parent_block_id else None
                    parent_map[orig_cid] = pid_str
                    parent_map[cid_str] = pid_str
                    found_cids.add(orig_cid)
                    found_cids.add(cid_str)
                    _CHUNK_PARENT_CACHE.set(orig_cid, pid_str or "__none__")
                    _CHUNK_PARENT_CACHE.set(cid_str, pid_str or "__none__")

                # 兼容兜底：对于在 DocumentChunk 中未查到的 chunk，尝试查 PG public.document_chunk 表（应对存量数据）
                pg_check_succeeded = True
                unfound_cids = [str(cid) for cid in missing_chunk_ids if str(cid) not in found_cids]
                if unfound_cids:
                    try:
                        from app.infra.pg import get_pg_pool

                        pool = get_pg_pool()
                        if pool:
                            async with pool.acquire() as pg_conn:
                                pg_rows = await pg_conn.fetch(
                                    "SELECT chunk_id, parent_chunk_id FROM public.document_chunk WHERE chunk_id = ANY($1::varchar[])",
                                    unfound_cids,
                                )
                                for r in pg_rows:
                                    cid_str = str(r["chunk_id"])
                                    pid_str = (
                                        str(r["parent_chunk_id"]) if r["parent_chunk_id"] else None
                                    )
                                    parent_map[cid_str] = pid_str
                                    found_cids.add(cid_str)
                                    _CHUNK_PARENT_CACHE.set(cid_str, pid_str or "__none__")
                        else:
                            pg_check_succeeded = False
                    except Exception as pg_err:
                        pg_check_succeeded = False
                        logger.debug("fallback to pg document_chunk failed", error=str(pg_err))

                # 未查到的 chunk 标记防止穿透（仅在正常完成检索且确认无记录时写入负缓存，避免瞬时池错误造成缓存污染）
                for cid in missing_chunk_ids:
                    cid_str = str(cid)
                    if cid_str not in found_cids:
                        parent_map[cid_str] = None
                        if pg_check_succeeded:
                            _CHUNK_PARENT_CACHE.set(cid_str, "__none__")

        # 3. 收集所有需要的大块 parent_id，优先查内容缓存
        parent_contents: dict[str, dict[str, str | None]] = {}
        parent_ids_to_fetch: set[Any] = set()
        for pid in parent_map.values():
            if pid:
                cached_content = _PARENT_CONTENT_CACHE.get(str(pid))
                if cached_content is not None:
                    parent_contents[str(pid)] = cached_content
                else:
                    parent_ids_to_fetch.add(pid)

        # 4. 仅对未命中内容缓存的 parent_id 查库并回填
        if parent_ids_to_fetch:
            from app.common.utils import stable_id_to_int

            pid_to_query_map = {stable_id_to_int(pid): str(pid) for pid in parent_ids_to_fetch}
            p_query_ids = list(pid_to_query_map.keys())
            async with _ensure_session(session) as s:
                p_result = await s.execute(
                    select(
                        DocumentParentBlock.id,
                        DocumentParentBlock.parent_text,
                        DocumentParentBlock.section_path,
                    ).where(DocumentParentBlock.id.in_(p_query_ids))
                )
                for prow in p_result.all():
                    parent_text = getattr(prow, "parent_text", None) or getattr(
                        prow, "chunk_text", ""
                    )
                    content_dict = {
                        "text": parent_text or "",
                        "path": getattr(prow, "section_path", "") or "",
                    }
                    orig_pid = pid_to_query_map.get(prow.id, str(prow.id))
                    parent_contents[orig_pid] = content_dict
                    parent_contents[str(prow.id)] = content_dict
                    _PARENT_CONTENT_CACHE.set(orig_pid, content_dict)
                    _PARENT_CONTENT_CACHE.set(str(prow.id), content_dict)

            # 兼容兜底：对于在 DocumentParentBlock 中未查到的 parent_id，尝试查 PG public.document_chunk 表
            unfound_pids = [
                str(pid) for pid in parent_ids_to_fetch if str(pid) not in parent_contents
            ]
            if unfound_pids:
                try:
                    from app.infra.pg import get_pg_pool

                    pool = get_pg_pool()
                    if pool:
                        async with pool.acquire() as pg_conn:
                            pg_rows = await pg_conn.fetch(
                                "SELECT chunk_id, content, section_title FROM public.document_chunk WHERE chunk_id = ANY($1::varchar[])",
                                unfound_pids,
                            )
                            for r in pg_rows:
                                content_dict = {
                                    "text": r["content"] or "",
                                    "path": r["section_title"] or "",
                                }
                                parent_contents[str(r["chunk_id"])] = content_dict
                                _PARENT_CONTENT_CACHE.set(str(r["chunk_id"]), content_dict)
                except Exception as pg_err:
                    logger.debug(
                        "fallback to pg document_chunk for parent text failed", error=str(pg_err)
                    )

        # 2. 按 Parent ID 分组聚合
        parent_groups: dict[str, list[Evidence]] = {}
        elevated_evidences = []

        def _get_sort_score(e: Evidence) -> float:
            if e.rerank_score is not None and e.rerank_score > 0.0:
                return e.rerank_score
            return e.score or 0.0

        for ev in evidences:
            if not getattr(ev, "child_chunk_id", None):
                ev.child_chunk_id = str(ev.chunk_id)
            if not getattr(ev, "child_chunk_text", None):
                ev.child_chunk_text = ev.content

            if ev.source_type != "document":
                elevated_evidences.append(ev)
                continue

            parent_id = parent_map.get(str(ev.chunk_id))
            if parent_id and parent_id in parent_contents:
                if parent_id not in parent_groups:
                    parent_groups[parent_id] = []
                parent_groups[parent_id].append(ev)
            else:
                if parent_id:
                    with contextlib.suppress(ValueError, TypeError):
                        ev.parent_block_id = int(parent_id)
                elevated_evidences.append(ev)

        # 3. 聚合计算得分与合并文本
        for parent_id, children in parent_groups.items():
            best_child = max(children, key=_get_sort_score)

            # parent_contents 的值为 str | None（缓存与兜底查询都可能写入 None），
            # 统一收敛为空串，避免下游 len()/切片/拼接遇到 None。
            content = parent_contents[parent_id]["text"] or ""
            path = parent_contents[parent_id]["path"] or ""

            final_content = f"【章节路径：{path}】\n{content}" if path else content

            # truncate to parent_evidence_max_chars
            max_chars = settings.rag.parent_evidence_max_chars
            if max_chars > 0 and len(final_content) > max_chars:
                final_content = final_content[:max_chars] + "..."

            # 复用 best_child 作为基座，记录命中子块，提升内容为父块完整上下文
            best_child.child_chunk_id = str(best_child.chunk_id)
            best_child.child_chunk_text = best_child.child_chunk_text or best_child.content
            best_child.content = final_content
            with contextlib.suppress(ValueError, TypeError):
                best_child.parent_block_id = int(parent_id)
            # 保留最初始的 RRF 或 BM25 分数（original_score 默认为 0.0，非 None）
            if best_child.original_score == 0.0:
                best_child.original_score = best_child.score

            elevated_evidences.append(best_child)

        return sorted(elevated_evidences, key=_get_sort_score, reverse=True)
