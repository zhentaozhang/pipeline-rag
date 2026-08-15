"""MinIO 对象存储客户端"""

import asyncio

import structlog
from minio import Minio

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry

logger = structlog.get_logger(__name__)
settings = get_settings()

_client: Minio | None = None
_minio_breaker = CircuitBreakerRegistry.get_or_register(
    "minio",
    CircuitBreakerConfig(
        name="minio",
        failure_threshold=3,
        recovery_timeout=15.0,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)


def init_minio() -> None:
    """在 lifespan 启动时调用，初始化 MinIO 客户端并确保 Bucket 存在"""
    global _client
    _client = Minio(
        endpoint=settings.minio.endpoint,
        access_key=settings.minio.access_key,
        secret_key=settings.minio.secret_key,
        secure=settings.minio.secure,
    )
    bucket = settings.minio.bucket
    if not _client.bucket_exists(bucket):
        _client.make_bucket(bucket)
        logger.info("minio bucket created", bucket=bucket)
    else:
        logger.info("minio bucket exists", bucket=bucket)


def close_minio() -> None:
    """lifespan 关闭时调用（MinIO SDK 无需显式关闭）"""
    global _client
    _client = None


def get_minio() -> Minio:
    if _client is None:
        raise RuntimeError("MinIO not initialized. Call init_minio() first.")
    return _client


async def bucket_exists(bucket_name: str) -> bool:
    client = get_minio()
    async with _minio_breaker:
        return await asyncio.to_thread(client.bucket_exists, bucket_name)
    return False


async def upload_bytes(
    object_name: str, data: bytes, content_type: str = "application/octet-stream"
) -> str:
    """上传字节数据到 MinIO"""
    import io

    client = get_minio()
    data_stream = io.BytesIO(data)
    length = len(data)

    def _do_upload():
        client.put_object(
            bucket_name=settings.minio.bucket,
            object_name=object_name,
            data=data_stream,
            length=length,
            content_type=content_type or "application/octet-stream",
        )

    async with _minio_breaker:
        await asyncio.to_thread(_do_upload)
    logger.info("bytes uploaded to minio", object_name=object_name)
    return object_name


async def upload_file(
    object_name: str, file_path: str, content_type: str = "application/octet-stream"
) -> str:
    """上传文件到 MinIO，返回 object_name"""
    client = get_minio()
    async with _minio_breaker:
        await asyncio.to_thread(
            client.fput_object,
            bucket_name=settings.minio.bucket,
            object_name=object_name,
            file_path=file_path,
            content_type=content_type,
        )
    logger.info("file uploaded to minio", object_name=object_name)
    return object_name


async def download_bytes(object_name: str) -> bytes:
    """下载对象原始字节"""
    client = get_minio()

    def _do_download():
        response = client.get_object(settings.minio.bucket, object_name)
        data = response.read()
        response.close()
        return data

    try:
        async with _minio_breaker:
            data = await asyncio.to_thread(_do_download)
    except Exception as e:
        logger.error(
            "minio download_bytes failed", object_name=object_name, error=str(e), exc_info=True
        )
        raise
    return data


async def delete_object(object_name: str) -> None:
    """删除单个对象"""
    client = get_minio()
    async with _minio_breaker:
        await asyncio.to_thread(client.remove_object, settings.minio.bucket, object_name)
    logger.info("minio object deleted", object_name=object_name)


async def delete_objects(prefix: str) -> None:
    """批量删除前缀匹配的对象"""
    client = get_minio()
    from minio.deleteobjects import DeleteObject

    def _do_delete() -> None:
        objects_to_delete = client.list_objects(
            settings.minio.bucket, prefix=prefix, recursive=True
        )
        delete_obj_list = [DeleteObject(obj.object_name) for obj in objects_to_delete]

        if delete_obj_list:
            errors = client.remove_objects(settings.minio.bucket, delete_obj_list)
            for error in errors:
                logger.error("minio delete_objects error", error=error)
            logger.info("minio objects deleted", prefix=prefix, count=len(delete_obj_list))

    async with _minio_breaker:
        await asyncio.to_thread(_do_delete)
