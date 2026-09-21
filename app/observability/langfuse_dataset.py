"""Langfuse Dataset 同步适配层（golden dataset → Langfuse Dataset）

- ensure_dataset：创建 dataset，已存在则忽略（create_dataset 非幂等）。
- upsert_items：按 item id 幂等 upsert（Langfuse 按 id 去重）。
- record_to_item：把 rag_evaluation_dataset 的 ORM 记录映射为 Langfuse item。
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any


class LangfuseDatasetSync:
    def __init__(self, client: Any) -> None:
        self._client = client

    def ensure_dataset(
        self,
        name: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # 数据集已存在（create_dataset 非幂等，重名 raise）——忽略，后续按 name 追加 item
        with suppress(Exception):
            self._client.create_dataset(
                name=name, description=description, metadata=metadata
            )

    def upsert_items(self, dataset_name: str, items: list[dict[str, Any]]) -> None:
        for item in items:
            self._client.create_dataset_item(
                dataset_name=dataset_name,
                id=item["id"],
                input=item["input"],
                expected_output=item.get("expected_output"),
                metadata=item.get("metadata"),
            )


def record_to_item(record: Any) -> dict[str, Any]:
    """rag_evaluation_dataset ORM 记录 → Langfuse dataset item"""
    try:
        contexts = json.loads(record.contexts) if record.contexts else []
    except (TypeError, ValueError):
        contexts = []
    return {
        "id": f"rag-{record.id}",
        "input": {"question": record.question, "contexts": contexts},
        "expected_output": {"ground_truth": record.ground_truth},
        "metadata": {
            "exchange_id": record.exchange_id,
            "conversation_id": record.conversation_id,
            "source_type": record.source_type,
        },
    }


async def sync_golden_dataset(
    db: Any,
    client: Any,
    *,
    dataset_name: str = "rag-golden",
    only_active: bool = True,
) -> int:
    """把 rag_evaluation_dataset（golden set）同步到 Langfuse Dataset，返回同步条数。"""
    from sqlalchemy import select

    from app.db.models.rag_observability import RagEvaluationDataset

    stmt = select(RagEvaluationDataset)
    if only_active:
        stmt = stmt.where(RagEvaluationDataset.status == 1)
    records = (await db.execute(stmt)).scalars().all()

    items = [record_to_item(r) for r in records]
    sync = LangfuseDatasetSync(client)
    sync.ensure_dataset(dataset_name, description="RAG 人工标注 golden dataset")
    sync.upsert_items(dataset_name, items)
    return len(items)
