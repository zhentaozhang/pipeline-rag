"""S3 数据源连接器（P3-3）

扫描 S3 兼容存储（AWS S3 / 其他 S3 兼容服务）的指定 bucket/prefix，
将文档导入到本地并触发文档处理流水线。

复用 minio SDK（S3 协议兼容），与项目对象存储保持一致。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import structlog

from app.config import get_settings
from app.document.connectors.base import ConnectorFile, DocumentConnector

logger = structlog.get_logger(__name__)


class S3Connector(DocumentConnector):
    """S3 连接器：list + fetch"""

    def __init__(self) -> None:
        from minio import Minio

        settings = get_settings().s3_connector
        self._bucket = settings.bucket
        self._prefix = settings.prefix
        endpoint = settings.endpoint.strip()
        secure = endpoint.startswith("https")
        if "://" in endpoint:
            endpoint = endpoint.split("://", 1)[1].rstrip("/")
        self._client = Minio(
            endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=secure,
        )

    async def list_files(self) -> list[ConnectorFile]:
        """列出 bucket 下 prefix 内的对象（异步封装同步 SDK）"""
        return await asyncio.to_thread(self._list_files_sync)

    def _list_files_sync(self) -> list[ConnectorFile]:
        files: list[ConnectorFile] = []
        try:
            objects = self._client.list_objects(self._bucket, prefix=self._prefix, recursive=True)
            for obj in objects:
                if obj.object_name.endswith("/"):  # 跳过目录占位
                    continue
                files.append(
                    ConnectorFile(
                        remote_key=obj.object_name,
                        name=Path(obj.object_name).name,
                        size=obj.size,
                    )
                )
        except Exception as e:
            logger.error("s3 list failed", bucket=self._bucket, prefix=self._prefix, error=str(e))
            raise
        return files

    async def fetch_to_local(self, file: ConnectorFile, dest_dir: Path) -> Path:
        """下载对象到本地（保持目录结构，避免同名覆盖）"""
        local_path = dest_dir / file.remote_key.replace("/", "__")
        return await asyncio.to_thread(self._fetch_sync, file, local_path)

    def _fetch_sync(self, file: ConnectorFile, local_path: Path) -> Path:
        self._client.fget_object(self._bucket, file.remote_key, str(local_path))
        return local_path


async def import_from_s3(
    scope_code: str = "",
    tags: str = "",
    tenant_id: str = "default",
) -> dict[str, object]:
    """S3 导入入口：扫描 → 过滤类型 → 下载 → 转存 MinIO → 创建元数据 → 触发流水线。返回导入报告。"""
    import mimetypes
    from typing import Any

    from app.config import get_settings

    settings = get_settings()
    connector_cfg = settings.s3_connector
    if not connector_cfg.enabled:
        return {"enabled": False, "skipped": True, "reason": "CONNECTOR_S3_ENABLED=false"}

    from app.db.repositories.knowledge_repository import KnowledgeRepository
    from app.db.session import get_session_factory, init_db

    session_factory = get_session_factory()
    if session_factory is None:
        await init_db()
        session_factory = get_session_factory()

    if session_factory is None:
        raise RuntimeError("Failed to initialize database session factory")

    scope_name = ""
    if scope_code:
        async with session_factory() as db:
            scope = await KnowledgeRepository.get_scope_by_code(db, scope_code)
            if not scope:
                raise ValueError(f"Knowledge scope not found: {scope_code}")
            scope_name = scope.scope_name or ""

    allowed = [t.strip().lower() for t in connector_cfg.file_types.split(",") if t.strip()]
    connector = S3Connector()

    all_files = await connector.list_files()
    targets = [f for f in all_files if connector.supports(f.name, allowed)]

    report: dict[str, Any] = {
        "total": len(all_files),
        "importable": len(targets),
        "imported": 0,
        "skipped": 0,
        "errors": [],
    }

    if not targets:
        return report

    max_size_bytes = 200 * 1024 * 1024  # 默认 200MB 上限防 OOM

    from app.document.connectors.base import process_connector_file

    with tempfile.TemporaryDirectory(prefix=connector_cfg.temp_dir) as tmp:
        tmp_dir = Path(tmp)
        for file in targets[: connector_cfg.batch_size]:
            try:
                if file.size > max_size_bytes:
                    logger.warning(
                        "s3 file exceeds 200MB limit, skipped", key=file.remote_key, size=file.size
                    )
                    report["errors"].append(
                        {
                            "key": file.remote_key,
                            "error": f"File size exceeds 200MB: {file.size} bytes",
                        }
                    )
                    continue

                local_path = await connector.fetch_to_local(file, tmp_dir)
                content = local_path.read_bytes()
                mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"

                res = await process_connector_file(
                    session_factory=session_factory,
                    filename=file.name,
                    content=content,
                    mime_type=mime_type,
                    scope_code=scope_code,
                    scope_name=scope_name,
                    tags=tags,
                    tenant_id=tenant_id,
                    source_label="S3",
                    detail={"remoteKey": file.remote_key},
                    max_size_bytes=max_size_bytes,
                )

                if res.status == "imported":
                    report["imported"] += 1
                    logger.info(
                        "s3 document imported",
                        key=file.remote_key,
                        doc_id=res.doc_id,
                        task_id=res.task_id,
                    )
                elif res.status == "skipped":
                    report["skipped"] += 1
                else:
                    report["errors"].append({"key": file.remote_key, "error": res.error})
            except Exception as e:
                report["errors"].append({"key": file.remote_key, "error": str(e)})
                logger.warning("s3 import failed", key=file.remote_key, error=str(e))

    return report
