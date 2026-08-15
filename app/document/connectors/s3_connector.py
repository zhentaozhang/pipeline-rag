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
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.endpoint.startswith("https"),
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


async def import_from_s3() -> dict[str, object]:
    """S3 导入入口：扫描 → 过滤类型 → 下载 → 触发流水线。返回导入报告。"""
    from typing import Any

    from app.config import get_settings

    settings = get_settings()
    connector_cfg = settings.s3_connector
    if not connector_cfg.enabled:
        return {"enabled": False, "skipped": True, "reason": "CONNECTOR_S3_ENABLED=false"}

    from app.infra.id_generator import next_id

    allowed = [t.strip().lower() for t in connector_cfg.file_types.split(",") if t.strip()]
    connector = S3Connector()

    all_files = await connector.list_files()
    targets = [f for f in all_files if connector.supports(f.name, allowed)]

    report: dict[str, Any] = {
        "total": len(all_files),
        "importable": len(targets),
        "imported": 0,
        "errors": [],
    }

    if not targets:
        return report

    from app.document.tasks import trigger_document_pipeline

    with tempfile.TemporaryDirectory(prefix=connector_cfg.temp_dir) as tmp:
        tmp_dir = Path(tmp)
        for file in targets[: connector_cfg.batch_size]:
            try:
                local_path = await connector.fetch_to_local(file, tmp_dir)
                doc_id = next_id()
                task_id = trigger_document_pipeline(str(doc_id), str(local_path))
                report["imported"] += 1
                logger.info(
                    "s3 document imported",
                    key=file.remote_key,
                    doc_id=doc_id,
                    task_id=task_id,
                )
            except Exception as e:
                report["errors"].append({"key": file.remote_key, "error": str(e)})
                logger.warning("s3 import failed", key=file.remote_key, error=str(e))

    return report
