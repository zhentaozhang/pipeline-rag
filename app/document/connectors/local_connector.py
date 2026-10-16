"""本地离线目录数据源连接器（支持企业离线文件夹扫描导入）"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import structlog

from app.document.connectors.base import ConnectorFile, DocumentConnector

logger = structlog.get_logger(__name__)

DEFAULT_ALLOWED_EXTENSIONS = [
    ".pdf",
    ".doc",
    ".docx",
    ".txt",
    ".md",
    ".html",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
]


class LocalDirectoryConnector(DocumentConnector):
    """本地离线目录连接器：递归遍历本地文件夹中的文档并导入系统"""

    def __init__(
        self,
        base_dir: str | Path,
        allowed_extensions: list[str] | None = None,
        max_files: int = 500,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.allowed_extensions = [
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in (allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS)
        ]
        self.max_files = max_files

    async def list_files(self) -> list[ConnectorFile]:
        """异步列出目录下的所有合法文件"""
        return await asyncio.to_thread(self._scan_sync)

    def _scan_sync(self) -> list[ConnectorFile]:
        if not self.base_dir.exists() or not self.base_dir.is_dir():
            logger.warning(
                "local directory does not exist or not a directory", path=str(self.base_dir)
            )
            return []

        results: list[ConnectorFile] = []
        for root, _, filenames in os.walk(self.base_dir):
            for fname in sorted(filenames):
                if fname.startswith((".", "~$")):
                    continue  # 跳过隐藏文件和 Office 临时文件
                ext = os.path.splitext(fname)[1].lower()
                if ext not in self.allowed_extensions:
                    continue
                file_path = Path(root) / fname
                try:
                    size = file_path.stat().st_size
                except OSError:
                    size = 0
                results.append(
                    ConnectorFile(
                        remote_key=str(file_path.resolve()),
                        name=fname,
                        size=size,
                    )
                )
                if len(results) >= self.max_files:
                    logger.info(
                        "reached max files limit during directory scan", limit=self.max_files
                    )
                    return results

        logger.info("local directory scan completed", count=len(results), path=str(self.base_dir))
        return results

    async def fetch_to_local(self, file: ConnectorFile, dest_dir: Path) -> Path:
        """从源目录复制到处理临时目录"""
        src_path = Path(file.remote_key)
        if not src_path.exists():
            raise FileNotFoundError(f"Source file not found: {src_path}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / file.name

        await asyncio.to_thread(shutil.copy2, str(src_path), str(dest_path))
        return dest_path


async def import_from_local_directory(
    directory_path: str | Path,
    scope_code: str = "",
    tags: str = "",
    tenant_id: str = "default",
) -> dict:
    """遍历本地目录并触发流水线批量导入"""
    import mimetypes

    from app.db.session import get_session_factory, init_db

    session_factory = get_session_factory()
    if session_factory is None:
        await init_db()
        session_factory = get_session_factory()

    if session_factory is None:
        raise RuntimeError("Failed to initialize database session factory")

    from app.db.repositories.knowledge_repository import KnowledgeRepository

    scope_name = ""
    if scope_code:
        async with session_factory() as db:
            scope = await KnowledgeRepository.get_scope_by_code(db, scope_code)
            if not scope:
                raise ValueError(f"Knowledge scope not found: {scope_code}")
            scope_name = scope.scope_name or ""

    connector = LocalDirectoryConnector(directory_path)
    files = await connector.list_files()
    if not files:
        return {"scanned": 0, "imported": 0, "skipped": 0, "message": "No valid documents found"}

    imported = 0
    skipped: list[dict] = []
    errors: list[dict] = []
    max_size_bytes = 200 * 1024 * 1024  # 默认 200MB 上限防 OOM

    from app.document.connectors.base import process_connector_file

    for cf in files:
        try:
            file_path = Path(cf.remote_key)
            if cf.size > max_size_bytes:
                logger.warning("file exceeds maximum limit, skipped", file=cf.name, size=cf.size)
                errors.append(
                    {"file": cf.name, "error": f"File size exceeds 200MB: {cf.size} bytes"}
                )
                continue

            with file_path.open("rb") as f:
                content = f.read(max_size_bytes + 1)

            mime_type = mimetypes.guess_type(cf.name)[0] or "application/octet-stream"

            res = await process_connector_file(
                session_factory=session_factory,
                filename=cf.name,
                content=content,
                mime_type=mime_type,
                scope_code=scope_code,
                scope_name=scope_name,
                tags=tags,
                tenant_id=tenant_id,
                source_label="本地离线目录",
                max_size_bytes=max_size_bytes,
            )

            if res.status == "imported":
                imported += 1
            elif res.status == "skipped":
                skipped.append({"file": cf.name, "doc_id": res.doc_id, "reason": res.reason})
            else:
                errors.append({"file": cf.name, "error": res.error})
        except Exception as e:
            logger.error("failed to import local file", file=cf.name, error=str(e))
            errors.append({"file": cf.name, "error": str(e)})

    return {
        "scanned": len(files),
        "imported": imported,
        "skipped": len(skipped),
        "errors": errors,
    }
