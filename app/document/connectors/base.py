"""文档数据源连接器抽象（P3-3）

统一模式：列出文件 → 下载到本地 → 触发文档处理流水线。
首个实现为 S3 连接器（与 MinIO 同构，S3 协议兼容），后续可扩展 Confluence/网页爬虫。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConnectorFile:
    """连接器发现的一个待导入文件"""

    remote_key: str  # 远程对象键（S3 key / URL / 页面 id）
    name: str  # 文件名（含扩展名，用于类型判断）
    size: int = 0


class DocumentConnector(ABC):
    """文档连接器基类"""

    @abstractmethod
    async def list_files(self) -> list[ConnectorFile]:
        """列出数据源中可导入的文件"""

    @abstractmethod
    async def fetch_to_local(self, file: ConnectorFile, dest_dir: Path) -> Path:
        """下载文件到本地临时目录，返回本地路径"""

    def supports(self, name: str, file_types: list[str]) -> bool:
        """判断文件扩展名是否在允许清单内"""
        if not file_types:
            return True
        suffix = Path(name).suffix.lower()
        return suffix in file_types


@dataclass
class ConnectorImportResult:
    """单个连接器文件处理结果"""

    status: str  # "imported" | "skipped" | "error"
    doc_id: str | None = None
    task_id: str | None = None
    reason: str = ""
    error: str = ""


async def process_connector_file(
    session_factory,
    filename: str,
    content: bytes,
    mime_type: str,
    scope_code: str = "",
    scope_name: str = "",
    tags: str = "",
    tenant_id: str = "default",
    source_label: str = "离线连接器",
    detail: dict | None = None,
    max_size_bytes: int = 200 * 1024 * 1024,
    file_type_code: int | None = None,
) -> ConnectorImportResult:
    """连接器导入文档通用管线：
    1. 空文件与大小拦截
    2. 基于 (file_size, original_file_name, knowledge_scope_code) 查重秒传跳过
    3. MinIO 对象存储持久化
    4. Document 主表与 DocumentTask 任务落库 + save_log 审计
    5. 触发 Celery 流水线 (返回 task_id)
    """
    from sqlalchemy import select

    from app.common.enums import (
        BusinessStatus,
        DocumentFileTypeEnum,
        DocumentIndexStatusEnum,
        DocumentLogLevelEnum,
        DocumentOperatorTypeEnum,
        DocumentParseStatusEnum,
        DocumentStorageTypeEnum,
        DocumentStrategyStatusEnum,
        DocumentTaskEventTypeEnum,
        DocumentTaskStageEnum,
        DocumentTaskStatusEnum,
        DocumentTaskTypeEnum,
    )
    from app.db.models.document import Document as DocModel
    from app.db.models.document import DocumentTask
    from app.document.tasks import trigger_document_pipeline
    from app.infra.id_generator import next_id_int, next_id_str
    from app.manage.service.document_async_service import save_log
    from app.manage.service.storage_service import upload_original_file

    if not content:
        return ConnectorImportResult(status="skipped", reason="empty_file")

    if len(content) > max_size_bytes:
        return ConnectorImportResult(
            status="error",
            error=f"File size exceeds maximum limit of {max_size_bytes // (1024 * 1024)}MB",
        )

    # 查重检测
    async with session_factory() as db:
        dup_stmt = select(DocModel).where(
            DocModel.file_size == len(content),
            DocModel.original_file_name == filename,
            DocModel.knowledge_scope_code == scope_code,
            DocModel.status == 1,
        )
        existing_doc = (await db.execute(dup_stmt)).scalars().first()
        if (
            existing_doc
            and existing_doc.index_status == DocumentIndexStatusEnum.BUILD_SUCCESS.value
        ):
            return ConnectorImportResult(
                status="skipped",
                doc_id=existing_doc.doc_id,
                reason="already_exists",
            )

    doc_id = next_id_str()
    doc_internal_id = next_id_int()

    # 统一存入系统 MinIO 对象存储
    stored_info = await upload_original_file(doc_id, filename, content, mime_type)

    if file_type_code is None:
        file_ext = filename.split(".")[-1].lower() if "." in filename else ""
        ft_enum = DocumentFileTypeEnum.__members__.get(file_ext.upper())
        if ft_enum:
            file_type_code = ft_enum.value
        elif mime_type == "text/markdown" or "markdown" in mime_type:
            file_type_code = DocumentFileTypeEnum.MD.value
        else:
            file_type_code = 0

    doc = DocModel(
        id=doc_internal_id,
        tenant_id=tenant_id,
        doc_id=doc_id,
        document_name=Path(filename).stem,
        original_file_name=filename,
        file_type=file_type_code,
        mime_type=mime_type,
        file_size=len(content),
        storage_type=DocumentStorageTypeEnum.MINIO.value,
        bucket_name=stored_info.bucket_name,
        object_name=stored_info.object_name,
        object_url=stored_info.object_url,
        parse_status=DocumentParseStatusEnum.PARSING.value,
        strategy_status=DocumentStrategyStatusEnum.WAIT_RECOMMEND.value,
        index_status=DocumentIndexStatusEnum.WAIT_BUILD.value,
        char_count=0,
        token_count=0,
        knowledge_scope_code=scope_code,
        knowledge_scope_name=scope_name,
        document_tags=tags,
        status=BusinessStatus.YES.value,
    )

    task_id_val = next_id_str()
    task = DocumentTask(
        id=next_id_int(),
        task_id=task_id_val,
        doc_id=doc_id,
        task_type=str(DocumentTaskTypeEnum.PARSE_ROUTE.value),
        stage=str(DocumentTaskStageEnum.FILE_UPLOAD.value),
        status=DocumentTaskStatusEnum.SUCCESS.value,
    )

    log_detail = {"originalFileName": filename, "fileSize": len(content)}
    if detail:
        log_detail.update(detail)

    async with session_factory() as db, db.begin():
        db.add(doc)
        db.add(task)
        await db.flush()
        await save_log(
            db,
            str(task.id),
            doc_internal_id,
            stage_type=DocumentTaskStageEnum.FILE_UPLOAD.value,
            event_type=DocumentTaskEventTypeEnum.COMPLETE.value,
            log_level=DocumentLogLevelEnum.INFO.value,
            operator_type=DocumentOperatorTypeEnum.SYSTEM.value,
            operator_id="system",
            content=f"{source_label}文档导入完成，已转存至 MinIO 并进入流水线。",
            detail=log_detail,
        )

    task_id = trigger_document_pipeline(doc_id, stored_info.object_name)
    return ConnectorImportResult(status="imported", doc_id=doc_id, task_id=task_id)
