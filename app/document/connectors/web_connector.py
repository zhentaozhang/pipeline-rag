"""网页爬虫连接器（P3-3 扩展）

抓取公开网站内容（sitemap / 种子 URL 递归发现），HTML → Markdown 后
进入文档处理流水线，与 S3 连接器共用 DocumentConnector 抽象。

约束：
- 仅支持公开可访问页面（无登录态）
- 尊重 robots.txt 的 Disallow 规则
- 默认限速（并发 + 间隔），避免对目标站点造成压力
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import structlog

from app.config import get_settings
from app.document.connectors.base import ConnectorFile, DocumentConnector

logger = structlog.get_logger(__name__)

_UA = "Mozilla/5.0 (compatible; PipelineRagBot/0.1; +https://github.com/pipeline-rag)"
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "spm"}
_SLUG_BLACKLIST = re.compile(r"[^\w\-.]+")


def normalize_url(url: str) -> str:
    """URL 规范化：去片段 + 去追踪参数 + host 小写，用于去重"""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def _is_same_domain(url: str, origin: str) -> bool:
    return urlsplit(url).netloc.lower() == urlsplit(origin).netloc.lower()


def _slugify(url: str, fallback: str) -> str:
    """URL → 文件名：host__path 模式"""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or fallback
    slug = _SLUG_BLACKLIST.sub("_", f"{parts.netloc}{path}")
    return slug.strip("_")[:150] or "page"


class WebConnector(DocumentConnector):
    """网页连接器：sitemap / 种子递归发现 + HTML→Markdown 抓取"""

    def __init__(self) -> None:
        settings = get_settings().web_connector
        self._seed_urls = [u for u in (settings.seed_urls or "").split(",") if u.strip()]
        self._sitemap_url = settings.sitemap_url or ""
        self._max_pages = settings.max_pages
        self._max_depth = settings.max_depth
        self._concurrency = settings.concurrency
        self._delay = settings.delay_seconds
        self._respect_robots = settings.respect_robots
        self._user_agent = settings.user_agent or _UA
        self._robots: dict[str, list[str]] = {}  # origin -> Disallow 前缀列表

    # ── 发现阶段 ────────────────────────────────────────────────

    async def list_files(self) -> list[ConnectorFile]:
        urls = await self._discover_urls()
        files = []
        for url in urls:
            files.append(ConnectorFile(remote_key=url, name=f"{_slugify(url, 'page')}.md"))
        return files

    async def _discover_urls(self) -> list[str]:
        if self._sitemap_url:
            urls = await self._fetch_sitemap(self._sitemap_url)
            if urls:
                return urls[: self._max_pages]
            logger.warning("sitemap empty or failed, falling back to seeds", sitemap=self._sitemap_url)

        # 种子 BFS 递归：同域 + 深度限制 + 页面数上限
        if not self._seed_urls:
            return []
        origins = {urlsplit(u).netloc for u in self._seed_urls}
        seen: set[str] = set()
        queue: list[tuple[str, int]] = [(u, 0) for u in self._seed_urls]
        sem = asyncio.Semaphore(self._concurrency)

        async def _crawl(url: str, depth: int) -> None:
            if url in seen or len(seen) >= self._max_pages:
                return
            seen.add(url)
            if len(seen) >= self._max_pages:
                return
            html = await self._fetch(url, sem)
            if not html:
                return
            if depth >= self._max_depth:
                return
            for link in _extract_links(html, url):
                norm = normalize_url(link)
                if not norm or norm in seen:
                    continue
                if any(_is_same_domain(norm, o) for o in origins):
                    queue.append((norm, depth + 1))

        # 简单的异步 BFS：逐层消费队列
        while queue and len(seen) < self._max_pages:
            level, queue = queue, []
            await asyncio.gather(*(_crawl(u, d) for u, d in level[: self._max_pages]))

        return list(seen)[: self._max_pages]

    async def _fetch_sitemap(self, sitemap_url: str) -> list[str]:
        """抓取 sitemap（支持 sitemap index 递归）"""
        from xml.etree import ElementTree as ET

        sem = asyncio.Semaphore(self._concurrency)
        html = await self._fetch(sitemap_url, sem)
        if not html:
            return []
        urls: list[str] = []
        try:
            root = ET.fromstring(html)
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//s:loc", ns):
                text = (loc.text or "").strip()
                if text:
                    if text.endswith(".xml"):
                        urls.extend(await self._fetch_sitemap(text))
                    else:
                        norm = normalize_url(text)
                        if norm:
                            urls.append(norm)
        except ET.ParseError:
            logger.warning("sitemap parse failed", url=sitemap_url)
        # 去重保序
        seen: set[str] = set()
        deduped: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        return deduped

    # ── 抓取阶段 ────────────────────────────────────────────────

    async def fetch_to_local(self, file: ConnectorFile, dest_dir: Path) -> Path:
        sem = asyncio.Semaphore(self._concurrency)
        html = await self._fetch(file.remote_key, sem)
        if not html:
            raise RuntimeError(f"fetch failed or empty: {file.remote_key}")

        import trafilatura

        markdown = trafilatura.extract(html, output_format="markdown", include_comments=False, include_tables=True)
        if not markdown or not markdown.strip():
            raise RuntimeError(f"no extractable content: {file.remote_key}")

        local_path = dest_dir / file.name
        local_path.write_text(
            f"# Source: {file.remote_key}\n\n---\n\n{markdown}\n",
            encoding="utf-8",
        )
        return local_path

    # ── 基础设施 ────────────────────────────────────────────────

    async def _fetch(self, url: str, sem: asyncio.Semaphore) -> str | None:
        if self._respect_robots and not await self._robots_allows(url):
            logger.info("blocked by robots.txt", url=url)
            return None
        async with sem:
            try:
                async with httpx.AsyncClient(
                    timeout=10.0, follow_redirects=True, headers={"User-Agent": self._user_agent}
                ) as client:
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        logger.info("http error", url=url, status=resp.status_code)
                        return None
                    if self._delay > 0:
                        await asyncio.sleep(self._delay)
                    return resp.text
            except httpx.HTTPError as e:
                logger.warning("fetch failed", url=url, error=str(e))
                return None

    async def _robots_allows(self, url: str) -> bool:
        origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
        if origin not in self._robots:
            disallows: list[str] = []
            try:
                async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                    resp = await client.get(f"{origin}/robots.txt", headers={"User-Agent": self._user_agent})
                if resp.status_code == 200:
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line.lower().startswith("disallow:"):
                            disallows.append(line.split(":", 1)[1].strip())
            except httpx.HTTPError:
                pass
            self._robots[origin] = disallows
        path = urlsplit(url).path or "/"
        return not any(path.startswith(d) for d in self._robots[origin] if d)


def _extract_links(html: str, base_url: str) -> list[str]:
    """从 HTML 提取站内链接（相对路径解析）"""
    from urllib.parse import urljoin

    from lxml import html as lh

    try:
        doc = lh.fromstring(html)
    except Exception:
        return []
    links = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        links.append(urljoin(base_url, href))
    return links


async def import_from_web() -> dict[str, object]:
    """网页导入入口：发现 → 过滤 → 下载 → 触发流水线。返回导入报告。"""
    from typing import Any

    from app.config import get_settings

    settings = get_settings()
    cfg = settings.web_connector
    if not cfg.enabled:
        return {"enabled": False, "skipped": True, "reason": "CONNECTOR_WEB_ENABLED=false"}

    from app.infra.id_generator import next_id

    connector = WebConnector()
    all_files = await connector.list_files()

    report: dict[str, Any] = {"total": len(all_files), "imported": 0, "errors": []}

    if not all_files:
        return report

    from app.document.tasks import trigger_document_pipeline

    with tempfile.TemporaryDirectory(prefix="rag-connector-web") as tmp:
        tmp_dir = Path(tmp)
        for file in all_files:
            try:
                local_path = await connector.fetch_to_local(file, tmp_dir)
                doc_id = next_id()
                task_id = trigger_document_pipeline(str(doc_id), str(local_path))
                report["imported"] += 1
                logger.info("web document imported", url=file.remote_key, doc_id=doc_id, task_id=task_id)
            except Exception as e:
                report["errors"].append({"url": file.remote_key, "error": str(e)})
                logger.warning("web import failed", url=file.remote_key, error=str(e))

    return report
