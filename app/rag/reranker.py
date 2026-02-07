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

        payload = {
            "model": settings.rerank.model,
            "query": query,
            "documents": [ev.content for ev in evidences],
            "return_documents": False,
            "top_n": settings.rerank.top_n,
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
            results_sorted = results_sorted[: settings.rerank.top_n]

            reranked = []
            for item in results_sorted:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(evidences):
                    ev = evidences[idx].model_copy()
                    relevance_score = float(item.get("relevance_score", 0.0))
                    ev.rerank_score = relevance_score
                    ev.rerank_model = settings.rerank.model
                    ev.rerank_query = query
                    ev.rerank_duration_ms = duration_ms
                    ev.rerank_original_index = idx
                    reranked.append(ev)

            return reranked

        except (Exception, asyncio.CancelledError):
            logger.exception("rerank failed, propagating to sub-question exception handler")
            raise
