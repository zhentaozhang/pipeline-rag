import re
import time
from dataclasses import dataclass

import structlog

from app.config import get_settings
from app.infra.minio import (
    bucket_exists,
    delete_object,
    download_bytes,
    upload_bytes,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class StoredObjectInfo:
    bucket_name: str
    object_name: str
    object_url: str


async def upload_original_file(
    document_id: str,
    original_file_name: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> StoredObjectInfo:
    """上传原始文档，返回存储信息"""
    object_prefix = getattr(settings.minio, "object_prefix", "documents")
    safe_filename = re.sub(r"[^\w\-.]", "_", original_file_name)
    object_name = f"{object_prefix}/{document_id}/{int(time.time() * 1000)}-{safe_filename}"
    await upload_bytes(object_name, file_bytes, content_type)
    object_url = _build_object_url(object_name)
    logger.info("original file uploaded", document_id=document_id, object_name=object_name)
    return StoredObjectInfo(
        bucket_name=settings.minio.bucket,
        object_name=object_name,
        object_url=object_url,
    )


async def download_object(object_name: str) -> bytes:
    """下载对象原始字节"""
    return await download_bytes(object_name)


async def delete_objects(object_name_list: list[str]) -> None:
    """按对象名列表逐个删除"""
    if not object_name_list:
        return
    valid_names = [n.strip() for n in object_name_list if n and n.strip()]
    if not valid_names:
        return
    if not await bucket_exists(settings.minio.bucket):
        return
    import asyncio as _asyncio

    for object_name in valid_names:
        await _asyncio.to_thread(delete_object, object_name)


def _build_object_url(object_name: str) -> str:
    endpoint = settings.minio.endpoint
    if endpoint.endswith("/"):
        endpoint = endpoint[:-1]
    return f"{endpoint}/{settings.minio.bucket}/{object_name}"
