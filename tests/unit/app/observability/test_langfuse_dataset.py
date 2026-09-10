"""LangfuseDatasetSync 适配层测试（mock langfuse 客户端）"""

import pytest

from app.observability.langfuse_dataset import (
    LangfuseDatasetSync,
    record_to_item,
    sync_golden_dataset,
)


class FakeClient:
    def __init__(self, create_dataset_raises=False):
        self.calls: list[tuple[str, dict]] = []
        self._create_dataset_raises = create_dataset_raises

    def create_dataset(self, **kwargs):
        self.calls.append(("create_dataset", kwargs))
        if self._create_dataset_raises:
            raise RuntimeError("dataset already exists")

    def create_dataset_item(self, **kwargs):
        self.calls.append(("create_dataset_item", kwargs))


def test_ensure_dataset_swallows_existing():
    client = FakeClient(create_dataset_raises=True)
    sync = LangfuseDatasetSync(client)
    sync.ensure_dataset("golden", description="d")  # 不抛异常
    assert client.calls[0][0] == "create_dataset"


def test_upsert_items_passes_id_input_expected_metadata():
    client = FakeClient()
    sync = LangfuseDatasetSync(client)
    items = [
        {
            "id": "rag-1",
            "input": {"question": "q1", "contexts": ["c1"]},
            "expected_output": {"ground_truth": "g1"},
            "metadata": {"source_type": "manual"},
        }
    ]
    sync.upsert_items("golden", items)

    item_call = next(c for c in client.calls if c[0] == "create_dataset_item")
    kwargs = item_call[1]
    assert kwargs["dataset_name"] == "golden"
    assert kwargs["id"] == "rag-1"
    assert kwargs["input"] == {"question": "q1", "contexts": ["c1"]}
    assert kwargs["expected_output"] == {"ground_truth": "g1"}
    assert kwargs["metadata"] == {"source_type": "manual"}


class _Record:
    id = 1
    question = "q"
    ground_truth = "gt"
    contexts = '["c1", "c2"]'
    exchange_id = 9
    conversation_id = "conv-1"
    source_type = "manual"


def test_record_to_item_maps_orm_to_langfuse_item():
    item = record_to_item(_Record())
    assert item["id"] == "rag-1"
    assert item["input"] == {"question": "q", "contexts": ["c1", "c2"]}
    assert item["expected_output"] == {"ground_truth": "gt"}
    assert item["metadata"]["exchange_id"] == 9
    assert item["metadata"]["conversation_id"] == "conv-1"
    assert item["metadata"]["source_type"] == "manual"


def test_record_to_item_tolerates_bad_contexts_json():
    r = _Record()
    r.contexts = "not-json"
    item = record_to_item(r)
    assert item["input"]["contexts"] == []


class _FakeResult:
    def __init__(self, records):
        self._records = records

    def scalars(self):
        return self

    def all(self):
        return self._records


class _FakeDB:
    def __init__(self, records):
        self._records = records

    async def execute(self, stmt):
        return _FakeResult(self._records)


@pytest.mark.asyncio
async def test_sync_golden_dataset_reads_db_and_upserts():
    client = FakeClient()
    db = _FakeDB([_Record()])
    count = await sync_golden_dataset(db, client, dataset_name="golden")

    assert count == 1
    assert any(c[0] == "create_dataset" for c in client.calls)
    item_calls = [c for c in client.calls if c[0] == "create_dataset_item"]
    assert len(item_calls) == 1
    assert item_calls[0][1]["id"] == "rag-1"
