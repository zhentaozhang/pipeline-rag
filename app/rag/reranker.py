"""
Rerank 精排客户端（SiliconFlow BGE-reranker-v2-m3 兼容协议）
"""

import asyncio
import threading

import httpx
import structlog

from app.chat.schema import Evidence
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_rerank_client: httpx.AsyncClient | None = None
_rerank_client_lock = threading.Lock()


def _get_rerank_client() -> httpx.AsyncClient:
    """模块级单例 httpx 客户端（避免每次 rerank 创建新连接池）"""
    global _rerank_client
    if _rerank_client is None:
        with _rerank_client_lock:
            if _rerank_client is None:
                connect_timeout = settings.rerank.connect_timeout_ms / 1000.0
                read_timeout = settings.rerank.read_timeout_ms / 1000.0
                _rerank_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout
                    )
                )
    return _rerank_client


class Reranker:
    """
    调用外部 Rerank API 对候选证据重新排序。
    SiliconFlow 兼容 OpenAI Reranking 协议。
    """

    async def rerank(self, query: str, evidences: list[Evidence]) -> list[Evidence]:
        """
        调用硅基流动（SiliconFlow）Reranker 接口，
        计算 query 与多段证据的相关性得分并重排。
        """
        if not settings.rerank.enabled or not evidences:
            return evidences

        logger.debug("reranking", count=len(evidences), query=query[:50])

        url = f"{settings.rerank.base_url.rstrip('/')}/rerank"
        headers = {
            "Authorization": f"Bearer {settings.rerank.api_key}",
            "Content-Type": "application/json",
        }

        # 送打分条数上限（score_cap，0=全部）：超出部分不送 API，但不得丢弃，
        # 追加在已评分结果之后（无分数），由下游按原有融合分兜底。
        cap = int(getattr(settings.rerank, "score_cap", 0) or 0)
        head = evidences[:cap] if 0 < cap < len(evidences) else evidences
        tail = evidences[len(head) :]

        if getattr(settings.rerank, "inject_title_breadcrumbs", False):
            docs_to_rerank = [
                f"【{ev.title}】\n{ev.content}"
                if ev.title and ev.title != "未知文档片段"
                else ev.content
                for ev in head
            ]
        else:
            docs_to_rerank = [ev.content for ev in head]
        payload = {
            "model": settings.rerank.model,
            "query": query,
            "documents": docs_to_rerank,
            "return_documents": False,
            # 让 API 返回全部候选的分数：截断留到下游（父块提升后再按 final_top_k 收口），
            # 否则候选在进入提升前就被砍掉，父块多样性直接受损。
            "top_n": len(docs_to_rerank),
        }

        try:
            import time

            start_ts = time.time()
            client = _get_rerank_client()
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            duration_ms = int((time.time() - start_ts) * 1000)

            results = data.get("results", [])
            # results format: [{"index": 0, "relevance_score": 0.8}, ...]

            # sort by relevance_score DESC, then limit to topN
            results_sorted = sorted(
                results,
                key=lambda r: -(float(r.get("relevance_score", 0))),
            )
            # 本地保留条数只看 keep_top_n（0 = 不截断）。
            # 旧配置项 top_n 只用于 API 侧"送打分条数"，不再兼任本地截断开关，
            # 否则 50 个候选重排完只留 10 个孩子进父块提升，且无任何日志。
            keep_top_n = int(getattr(settings.rerank, "keep_top_n", 0) or 0)
            if keep_top_n > 0:
                # keep_top_n 是"最终保留条数"硬上限：此时未送打分的尾巴也不再追加。
                results_sorted = results_sorted[:keep_top_n]
                tail = []

            reranked = []
            for item in results_sorted:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(head):
                    ev = head[idx].model_copy()
                    relevance_score = float(item.get("relevance_score", 0.0))
                    ev.rerank_score = relevance_score
                    ev.rerank_model = settings.rerank.model
                    ev.rerank_query = query
                    ev.rerank_duration_ms = duration_ms
                    ev.rerank_original_index = idx
                    reranked.append(ev)

            return reranked + [e.model_copy() for e in tail]

        except (Exception, asyncio.CancelledError):
            logger.exception("rerank failed, propagating to sub-question exception handler")
            raise
