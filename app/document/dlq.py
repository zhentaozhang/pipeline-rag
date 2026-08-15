"""
死信处理器：超过重试次数后执行最终补偿 + 告警
"""

from typing import Any

import structlog
from celery.signals import task_failure

logger = structlog.get_logger(__name__)


@task_failure.connect
def _on_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: Any = None,
    args: tuple | None = None,
    kwargs: dict | None = None,
    **kw: Any,
) -> None:
    """Celery 任务最终失败时触发（超过 max_retries）"""
    task_name = getattr(sender, "name", "")
    if not task_name.startswith("document."):
        return

    doc_id = _extract_doc_id(task_name, args)
    if not doc_id:
        logger.error("dlq: cannot extract doc_id", task_name=task_name, task_id=task_id)
        return

    logger.warning(
        "document pipeline task dead lettered",
        doc_id=doc_id,
        task_name=task_name,
        task_id=task_id,
        error=str(exception),
    )

    from app.document.tasks import _compensate, _infer_stage, _update_document_failed

    _compensate(doc_id, _infer_stage(task_name))
    _update_document_failed(doc_id, f"死信: {task_name} 超过最大重试次数 - {exception}")


def _extract_doc_id(task_name: str, args: tuple | None) -> str | None:
    if not args:
        return None
    if task_name == "document.parse":
        return str(args[0]) if len(args) > 0 else None
    if len(args) >= 2:
        return str(args[1])
    return None
