"""
MinerU 文档解析增强通道（P2-4）

背景：unstructured + MarkItDown 对扫描件/复杂表格/多栏版式弱；
MinerU（opendatalab，74k★）是 2026 文档解析标杆：版面分析/OCR/表格/公式 → Markdown。

接入方式（配置选择，全部容错——失败自动降级到现有 unstructured 路径）：
- Agent 轻量 API：/api/v1/agent/parse/file（免 token，≤10MB/20页）
- 精准解析 API：/api/v4/extract/task（需 token，≤200MB/200页）

用法：
    parser = MineruParser()
    markdown, meta = await parser.parse_pdf(file_path)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


@dataclass
class MineruResult:
    markdown: str = ""
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)


class MineruParser:
    """MinerU API 客户端（增强通道，失败抛异常由调用方降级）"""

    def __init__(self) -> None:
        settings = get_settings()
        self._enabled = settings.mineru.enabled
        self._base_url = settings.mineru.base_url.rstrip("/")
        self._api_key = settings.mineru.api_key
        self._mode = settings.mineru.mode  # agent | extract
        self._timeout = settings.mineru.timeout_seconds
        self._poll_interval = settings.mineru.poll_interval_seconds
        self._max_poll_retries = settings.mineru.max_poll_retries

    async def parse_pdf(self, file_path: str | Path) -> MineruResult:
        """解析 PDF（或图片），返回 Markdown 与元数据。失败抛异常。"""
        path = Path(file_path)
        if self._mode == "agent":
            return await self._parse_agent(path)
        return await self._parse_extract(path)

    # ── Agent 轻量解析（免 token）────────────────────────────────────────
    async def _parse_agent(self, path: Path) -> MineruResult:
        url = f"{self._base_url}/api/v1/agent/parse/file"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    url,
                    files={"file": (path.name, fh, "application/pdf")},
                )
            resp.raise_for_status()
            data = resp.json()
        task_id = (data.get("data") or {}).get("taskId") if isinstance(data.get("data"), dict) else None
        if not task_id:
            raise RuntimeError(f"MinerU agent parse failed: {data}")
        markdown, meta = await self._poll_result(task_id, result_endpoint="agent")
        return MineruResult(markdown=markdown, page_count=meta.get("page_count"), metadata=meta)

    # ── 精准解析 API（需 token）──────────────────────────────────────────
    async def _parse_extract(self, path: Path) -> MineruResult:
        url = f"{self._base_url}/api/v4/extract/task"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    url,
                    headers=headers,
                    data={"is_ocr": "false", "enable_formula": "true"},
                    files={"file": (path.name, fh, "application/pdf")},
                )
            resp.raise_for_status()
            data = resp.json()
        task_id = (data.get("data") or {}).get("taskId") if isinstance(data.get("data"), dict) else None
        if not task_id:
            raise RuntimeError(f"MinerU extract parse failed: {data}")
        markdown, meta = await self._poll_result(task_id, result_endpoint="extract")
        return MineruResult(markdown=markdown, page_count=meta.get("page_count"), metadata=meta)

    # ── 结果轮询 ─────────────────────────────────────────────────────────
    async def _poll_result(self, task_id: str, result_endpoint: str) -> tuple[str, dict]:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        if result_endpoint == "extract":
            result_url = f"{self._base_url}/api/v4/extract/result/{task_id}"
        else:
            result_url = f"{self._base_url}/api/v1/agent/parse/result/{task_id}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(self._max_poll_retries):
                await asyncio.sleep(self._poll_interval)
                try:
                    resp = await client.get(result_url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    state = data.get("state") or (data.get("data") or {}).get("state", "")
                    if state in ("succeeded", "done", "completed"):
                        full_data = data.get("data") if isinstance(data.get("data"), dict) else data
                        md = (
                            full_data.get("markdown")
                            or full_data.get("content")
                            or full_data.get("result", "")
                        )
                        if isinstance(md, list):
                            md = "\n".join(str(item) for item in md)
                        if not md:
                            raise RuntimeError(f"MinerU result empty: {data}")
                        meta = {"page_count": full_data.get("page_count")}
                        return str(md), meta
                    if state in ("failed", "error"):
                        raise RuntimeError(f"MinerU task failed: {data}")
                except httpx.HTTPStatusError as e:
                    if attempt == self._max_poll_retries - 1:
                        raise
                    logger.debug("mineru poll transient error", attempt=attempt, error=str(e))
                except Exception as e:
                    if attempt == self._max_poll_retries - 1:
                        raise
                    logger.debug("mineru poll retry", attempt=attempt, error=str(e))
        raise RuntimeError(f"MinerU poll timeout for task {task_id}")
