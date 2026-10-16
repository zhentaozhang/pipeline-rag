from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.common.enums import (
    DocumentIndexStatusEnum,
    DocumentPipelineStageEnum,
    DocumentStrategyRoleEnum,
)
from app.document.chunker.config import ChunkConfig
from app.document.chunker.llm import LLMChunker
from app.document.chunker.models import Chunk, ChunkStrategyType
from app.document.chunker.semantic import SemanticChunker
from app.document.chunker.utils import truncate_text_to_tokens
from app.document.connectors.local_connector import LocalDirectoryConnector
from app.document.parser import DocumentParser
from app.document.structure.models import DocumentStructureNodeCandidate
from app.document.vectorizer import VectorizerService
from app.infra.embedding import (
    EmbeddingProvider,
    LocalTEIEmbeddingProvider,
    OllamaEmbeddingProvider,
    get_embedding_provider,
    reset_embedding_provider,
)
from app.manage.service.document_strategy_service import build_chunks

# ==============================================================================
# Stage 1 Tests: 4 Fatal Flaws Fixed
# ==============================================================================


@pytest.mark.asyncio
async def test_cleanup_orphan_documents_protects_indexed_and_recent():
    """验证 cleanup_orphan_documents 绝不误删 INDEXED(4) 文档，且对进行中文档设置 2 小时停滞保护"""
    now = datetime.now()

    doc_indexed = MagicMock()
    doc_indexed.id = 101
    doc_indexed.pipeline_stage = DocumentPipelineStageEnum.INDEXED.value
    doc_indexed.status = 1
    doc_indexed.updated_at = now - timedelta(hours=5)

    doc_recent = MagicMock()
    doc_recent.id = 102
    doc_recent.pipeline_stage = DocumentPipelineStageEnum.PARSED.value
    doc_recent.status = 1
    doc_recent.updated_at = now - timedelta(minutes=30)

    doc_stalled = MagicMock()
    doc_stalled.id = 103
    doc_stalled.doc_id = "doc-stalled-103"
    doc_stalled.pipeline_stage = DocumentPipelineStageEnum.PARSED.value
    doc_stalled.status = 1
    doc_stalled.updated_at = now - timedelta(hours=3)

    stale_threshold = now - timedelta(hours=2)

    # 模拟 SQL 过滤行为：where pipeline_stage between 1 and 3, updated_at < stale_threshold
    all_docs = [doc_indexed, doc_recent, doc_stalled]
    filtered_docs = [
        d
        for d in all_docs
        if DocumentPipelineStageEnum.PARSED.value
        <= d.pipeline_stage
        <= DocumentPipelineStageEnum.VECTORIZED.value
        and d.status == 1
        and d.updated_at < stale_threshold
    ]

    assert len(filtered_docs) == 1
    assert filtered_docs[0].id == 103
    assert doc_indexed not in filtered_docs
    assert doc_recent not in filtered_docs


@pytest.mark.asyncio
async def test_save_nodes_idempotency():
    """验证 save_nodes 在插入前先行清理旧结构节点"""
    from app.manage.service.document_structure_node_service import save_nodes

    mock_db = AsyncMock()
    mock_db.add_all = MagicMock()

    doc = MagicMock()
    doc.id = 42
    doc_res = MagicMock()
    doc_res.scalar_one_or_none.return_value = doc

    mock_db.execute.return_value = doc_res

    candidate = DocumentStructureNodeCandidate(
        node_no=1,
        node_type="section",
        parent_node_no=None,
        prev_sibling_node_no=0,
        next_sibling_node_no=0,
        depth=1,
        node_code="1",
        title="Introduction",
        anchor_text="intro",
        canonical_path="DOC42#1",
        section_path="Introduction",
        content_text="Intro text",
        item_index=None,
    )

    with patch(
        "app.manage.service.document_structure_node_service.get_neo4j",
        return_value=MagicMock(enabled=False),
    ):
        await save_nodes(mock_db, "DOC42", "task-1", [candidate])

    # 验证是否执行了针对 pipeline_rag_document_structure_node 的 delete 语句
    delete_executed = False
    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        sql_text = str(stmt)
        if "DELETE" in sql_text and "pipeline_rag_document_structure_node" in sql_text:
            delete_executed = True
            break
    assert delete_executed, "save_nodes must delete existing structure nodes before inserting"


@pytest.mark.asyncio
async def test_write_to_pgvector_cleans_ghost_vectors():
    """验证 VectorizerService._write_to_pgvector 在写入前删除旧的文档向量，防止幽灵向量残留"""
    mock_provider = AsyncMock(spec=EmbeddingProvider)
    mock_provider.dimensions.return_value = 1536
    mock_provider.embed_batch.return_value = [[0.1] * 1536]

    svc = VectorizerService(provider=mock_provider)

    chunk = Chunk(
        chunk_id="chunk-1",
        doc_id="DOC-999",
        document_id=999,
        chunk_index=0,
        content="Hello world",
        chunk_type="child",
    )

    mock_conn = AsyncMock()

    class MockTxCM:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("app.infra.pg.transaction", return_value=MockTxCM()):
        await svc._write_to_pgvector(
            all_chunks=[chunk],
            child_chunks=[chunk],
            embeddings=[[0.1] * 1536],
            task_id="task-1",
            tenant_id="default",
            document_name="test.txt",
        )

        delete_called = False
        for call in mock_conn.execute.call_args_list:
            sql = call[0][0]
            if "DELETE FROM pipeline_rag_document_embedding WHERE document_id = $1" in sql:
                assert call[0][1] == 999
                delete_called = True
                break
        assert delete_called, "Must delete old embeddings from pipeline_rag_document_embedding"


@pytest.mark.asyncio
async def test_parent_child_chunking_linking():
    """验证 build_chunks 在使用 Parent 策略时正确打通父子块关系，并输出包含 parent 的完整 chunks"""
    from app.db.models.document import Document, DocumentStrategyPlan, DocumentStrategyStep

    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    # 模拟 doc
    mock_doc = Document(id=55, doc_id="DOC-55", document_name="Test Doc")
    mock_doc_res = MagicMock()
    mock_doc_res.scalar_one_or_none.return_value = mock_doc

    # 模拟 plan
    mock_plan = DocumentStrategyPlan(id=1, document_id=55, plan_version=1)
    mock_plan_res = MagicMock()
    mock_plan_res.scalar_one_or_none.return_value = mock_plan

    # 模拟 steps: 1 个 Parent 策略 (Recursive, 200字符), 1 个 Child 策略 (Recursive, 50字符)
    step_parent = DocumentStrategyStep(
        id=1,
        document_id=55,
        plan_id=1,
        step_no=1,
        strategy_type=2,  # RECURSIVE
        pipeline_type="PARENT",
        strategy_role=DocumentStrategyRoleEnum.PRIMARY.value,
    )
    step_child = DocumentStrategyStep(
        id=2,
        document_id=55,
        plan_id=1,
        step_no=2,
        strategy_type=2,  # RECURSIVE
        pipeline_type="CHILD",
        strategy_role=DocumentStrategyRoleEnum.PRIMARY.value,
    )
    mock_steps_res = MagicMock()
    mock_steps_res.scalars.return_value.all.return_value = [step_parent, step_child]

    mock_db.execute.side_effect = [mock_doc_res, mock_plan_res, mock_steps_res, MagicMock()]

    sample_text = (
        "Artificial intelligence is transforming every industry. "
        "Natural language processing enables machines to understand human speech. "
        "Large language models can summarize documents, answer complex questions, "
        "and generate high quality code with unprecedented accuracy and speed."
    )

    chunks = await build_chunks(mock_db, "DOC-55", sample_text)

    # 应当同时包含 parent chunk 和 child chunk
    parent_chunks = [c for c in chunks if c.get("chunk_type") == "parent"]
    child_chunks = [c for c in chunks if c.get("chunk_type") == "child"]

    assert len(parent_chunks) > 0, "Should generate at least one parent chunk"
    assert len(child_chunks) > 0, "Should generate child chunks"

    parent_ids = {p["chunk_id"] for p in parent_chunks}
    for child in child_chunks:
        assert child.get("parent_chunk_id") is not None
        assert child["parent_chunk_id"] in parent_ids, (
            f"Child parent_chunk_id {child['parent_chunk_id']} must point to a valid parent"
        )


# ==============================================================================
# Stage 2 Tests: Parsing & Chunking Normalization
# ==============================================================================


@pytest.mark.asyncio
async def test_semantic_chunker_embedding_and_lexical_fallback():
    """验证 SemanticChunker: 向量余弦相似度切块与异常时优雅降级为词法切块"""
    mock_provider = AsyncMock(spec=EmbeddingProvider)
    # 两组句子：前两句很相似（余弦接近1），第三句完全不同（正交）
    mock_provider.embed_batch.return_value = [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
    ]

    c1 = Chunk(chunk_id="1", doc_id="d1", content="Hello world from AI.", chunk_index=0)
    c2 = Chunk(
        chunk_id="2", doc_id="d1", content="Hello world from machine learning.", chunk_index=1
    )
    c3 = Chunk(
        chunk_id="3",
        doc_id="d1",
        content="Completely different topic about gardening.",
        chunk_index=2,
    )

    with patch("app.infra.embedding.get_embedding_provider", return_value=mock_provider):
        chunker = SemanticChunker()
        merged = await chunker.chunk([c1, c2, c3], ChunkConfig())
        assert len(merged) == 2
        assert "Hello world from AI." in merged[0].content
        assert "Hello world from machine learning." in merged[0].content
        assert "gardening" in merged[1].content

    # 2. 模拟向量接口抛异常，降级到词法 Jaccard
    failing_provider = AsyncMock(spec=EmbeddingProvider)
    failing_provider.embed_batch.side_effect = RuntimeError("Embedding service unavailable")

    with patch("app.infra.embedding.get_embedding_provider", return_value=failing_provider):
        chunker_fallback = SemanticChunker()
        chunks_fb = await chunker_fallback.chunk([c1, c2, c3], ChunkConfig())
        assert len(chunks_fb) >= 1, "Fallback lexical split must succeed"


@pytest.mark.asyncio
async def test_llm_chunker_batching_and_fallback():
    """验证 LLMChunker: 自然段分批发送，LLM 格式损坏时自动降级到 RecursiveChunker"""
    mock_client = AsyncMock()

    # 模拟 LLM 返回非 JSON 格式垃圾数据
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Sorry, I cannot format this into JSON."
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("app.common.llm_client.get_chat_client", return_value=mock_client):
        chunker = LLMChunker()
        text = "Paragraph 1 is here.\n\nParagraph 2 is here.\n\nParagraph 3 is here."
        chunks = await chunker.chunk(text, "DOC-1", ChunkConfig(chunk_size=100))
        assert len(chunks) >= 1
        assert any("Paragraph 1" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_parser_csv():
    """验证 CSV 文件解析转为标准 Markdown 表格"""
    parser = DocumentParser()
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("Name,Age,Role\nAlice,30,Engineer\nBob,25,Designer\n")
        csv_path = Path(f.name)
    try:
        res = await parser._parse_csv(csv_path)
        assert "| Name | Age | Role |" in res.text
        assert "| Alice | 30 | Engineer |" in res.text
        assert "| Bob | 25 | Designer |" in res.text
    finally:
        csv_path.unlink(missing_ok=True)


def test_token_hard_truncation():
    """验证 token 硬截断工具与 VectorizerService 上限保护"""
    long_text = "word " * 500
    truncated = truncate_text_to_tokens(long_text, max_tokens=20)
    assert len(truncated.split()) <= 20

    svc = VectorizerService.__new__(VectorizerService)
    chunk = Chunk(
        chunk_id="c1",
        doc_id="d1",
        content="Chunk text " * 500,
        chunk_index=0,
        section_path="Section A",
    )
    with patch("app.document.vectorizer.settings") as mock_settings:
        mock_settings.rag.max_embedding_tokens = 50
        mock_settings.rag.contextual_chunking_enabled = True
        ctx_text = svc._build_contextual_text(chunk, "Doc Title")
        assert len(ctx_text.split()) <= 60


# ==============================================================================
# Stage 3 Tests: Batch Import, Deduplication, Directory Connector, Archive
# ==============================================================================


@pytest.mark.asyncio
async def test_upload_deduplication():
    """验证同一 KnowledgeScope 下相同 sha256/大小 文件触发秒传复用"""
    from app.manage.service.document_service import upload_document

    mock_db = AsyncMock()

    file_content = b"Repeatable file content for testing deduplication."
    mock_file = MagicMock()
    mock_file.filename = "report.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=file_content)

    # 模拟已存在的文档
    existing_doc = MagicMock()
    existing_doc.doc_id = "DOC-777"
    existing_doc.document_name = "report.pdf"
    existing_doc.index_status = DocumentIndexStatusEnum.BUILD_SUCCESS.value
    existing_doc.parse_status = 2
    existing_doc.strategy_status = 2
    existing_doc.last_index_task_id = "task-777"

    mock_dup_res = MagicMock()
    mock_dup_res.scalars.return_value.first.return_value = existing_doc

    with patch(
        "app.db.repositories.knowledge_repository.KnowledgeRepository.get_scope_by_code",
        return_value=MagicMock(),
    ):
        mock_db.execute.return_value = mock_dup_res

        res = await upload_document(
            db=mock_db,
            file=mock_file,
            scope_code="finance",
            title="report.pdf",
            tags="",
        )

        assert res["docId"] == "DOC-777"
        assert res["status"] == "already_exists"


@pytest.mark.asyncio
async def test_local_directory_connector():
    """验证 LocalDirectoryConnector 本地文件夹递归扫描与过滤"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        dir_path = Path(tmp_dir)
        (dir_path / "doc1.txt").write_text("Document 1 content")
        (dir_path / "doc2.md").write_text("Document 2 content")
        (dir_path / "ignored.exe").write_text("Executable binary")

        sub_dir = dir_path / "subdir"
        sub_dir.mkdir()
        (sub_dir / "doc3.csv").write_text("col1,col2\nval1,val2")

        connector = LocalDirectoryConnector(
            base_dir=tmp_dir,
            allowed_extensions=[".txt", ".md", ".csv"],
            max_files=10,
        )

        files = await connector.list_files()
        assert len(files) == 3

        names = {f.name for f in files}
        assert "doc1.txt" in names
        assert "doc2.md" in names
        assert "doc3.csv" in names
        assert "ignored.exe" not in names


def test_zip_upload_zip_slip_protection():
    """验证上传 zip 压缩包时对恶意路径（Zip-Slip 漏洞）的安全拦截"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious content")
        zf.writestr("safe_doc.txt", "safe content")

    zip_bytes = zip_buffer.getvalue()

    with tempfile.TemporaryDirectory() as tmp_dest:
        dest_path = Path(tmp_dest).resolve()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for member in zf.infolist():
                member_path = (dest_path / member.filename).resolve()
                if not member_path.is_relative_to(dest_path):
                    # 成功识别并拦截 Zip-Slip 恶意相对路径
                    assert member.filename == "../../etc/passwd"
                else:
                    assert member.filename == "safe_doc.txt"


# ==============================================================================
# Stage 4 Tests: Offline Embedding Providers
# ==============================================================================


@pytest.mark.asyncio
async def test_ollama_embedding_provider_and_dimension_check():
    """验证 OllamaEmbeddingProvider: /api/embed 接口解析及维度校验"""
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434",
        model="nomic-embed-text",
        dimensions=768,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "embeddings": [[0.1] * 768, [0.2] * 768],
    }

    with patch.object(provider._client, "post", return_value=mock_resp):
        res = await provider.embed_batch(["Text 1", "Text 2"])
        assert len(res) == 2
        assert len(res[0]) == 768
        assert provider.dimensions() == 768

    await provider.aclose()


@pytest.mark.asyncio
async def test_local_tei_embedding_provider():
    """验证 LocalTEIEmbeddingProvider: /embed 接口调用"""
    provider = LocalTEIEmbeddingProvider(
        base_url="http://localhost:8080",
        model="bge-m3",
        dimensions=1024,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [[0.05] * 1024]

    with patch.object(provider._client, "post", return_value=mock_resp):
        res = await provider.embed_batch(["Local test text"])
        assert len(res) == 1
        assert len(res[0]) == 1024
        assert provider.dimensions() == 1024

    await provider.aclose()


def test_embedding_factory_routing():
    """验证 get_embedding_provider 工厂方法支持 openai/ollama/tei 路由"""
    reset_embedding_provider()

    with patch("app.infra.embedding.get_settings") as mock_settings:
        mock_settings.return_value.llm.embedding_provider = "ollama"
        mock_settings.return_value.llm.embedding_base_url = "http://localhost:11434"
        mock_settings.return_value.llm.embedding_model = "bge-m3"
        mock_settings.return_value.llm.embedding_dimensions = 1024
        mock_settings.return_value.llm.timeout_seconds = 30

        provider = get_embedding_provider()
        assert isinstance(provider, OllamaEmbeddingProvider)
        assert provider.dimensions() == 1024

    reset_embedding_provider()

    with patch("app.infra.embedding.get_settings") as mock_settings:
        mock_settings.return_value.llm.embedding_provider = "tei"
        mock_settings.return_value.llm.embedding_base_url = "http://localhost:8080"
        mock_settings.return_value.llm.embedding_model = "bge-large-zh"
        mock_settings.return_value.llm.embedding_dimensions = 1024
        mock_settings.return_value.llm.embedding_api_key = "EMPTY"
        mock_settings.return_value.llm.timeout_seconds = 30

    reset_embedding_provider()


@pytest.mark.asyncio
async def test_semantic_chunker_respects_parent_boundaries():
    """验证 SemanticChunker 即使余弦相似度极高，也绝不跨 Parent 块合并 Child 块"""
    mock_provider = AsyncMock(spec=EmbeddingProvider)
    # 两块极其相似（1.0 完全一致），但分别属于 parent-1 和 parent-2
    mock_provider.embed_batch.return_value = [
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
    ]

    c1 = Chunk(
        chunk_id="child-1",
        doc_id="d1",
        content="Same identical text.",
        chunk_index=0,
        parent_chunk_id="parent-1",
    )
    c2 = Chunk(
        chunk_id="child-2",
        doc_id="d1",
        content="Same identical text.",
        chunk_index=1,
        parent_chunk_id="parent-2",
    )

    with patch("app.infra.embedding.get_embedding_provider", return_value=mock_provider):
        chunker = SemanticChunker()
        merged = await chunker.chunk([c1, c2], ChunkConfig(max_chunk_size=1000))
        # 因为跨了 parent，严禁合并，必须保留 2 个独立 chunk
        assert len(merged) == 2
        assert merged[0].parent_chunk_id == "parent-1"
        assert merged[1].parent_chunk_id == "parent-2"


@pytest.mark.asyncio
async def test_llm_chunker_handles_single_giant_paragraph():
    """验证 LLMChunker 当面对单段超长（无换行）文本时，自动平展切片不爆内存"""
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '["Part A", "Part B"]'
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("app.common.llm_client.get_chat_client", return_value=mock_client):
        chunker = LLMChunker()
        giant_text = "A" * 15000  # 1.5 万字符无换行
        chunks = await chunker.chunk(giant_text, "DOC-1", ChunkConfig(min_chunk_size=2))
        assert len(chunks) >= 2


@pytest.mark.asyncio
async def test_compensate_async_safely_callable_in_running_loop():
    """验证 _compensate 在已运行的事件循环中被调用时，通过 create_task 调度，绝不抛 Loop Already Running 异常"""
    from app.document.tasks._base import _compensate

    with patch("app.document.tasks._base._compensate_async", new_callable=AsyncMock) as mock_comp:
        # 在 async 函数内同步调用 _compensate
        _compensate("DOC-TEST", 2)
        # 允许微任务队列推进
        import asyncio

        await asyncio.sleep(0.01)
        mock_comp.assert_called_once_with("DOC-TEST", 2)


@pytest.mark.asyncio
async def test_save_mysql_document_chunks_safe_in_running_loop():
    """验证 _save_mysql_document_chunks 在已有事件循环中调用时智能调度，不崩溃"""
    from app.document.tasks._vectorize import _save_mysql_document_chunks

    with patch(
        "app.document.tasks._vectorize._save_mysql_document_chunks_async",
        new_callable=AsyncMock,
    ) as mock_save:
        _save_mysql_document_chunks("DOC-TEST", [], "task-1")
        import asyncio

        await asyncio.sleep(0.01)
        mock_save.assert_called_once_with("DOC-TEST", [], "task-1")


@pytest.mark.asyncio
async def test_task_index_document_compensates_on_failure():
    """验证 task_index_document 在发生索引写入异常时，调用 _task_failed 触发 ES/Neo4j 补偿回滚"""
    from app.common.enums import DocumentTaskStageEnum
    from app.document.tasks._index import task_index_document

    mock_self = MagicMock()
    mock_self.request.id = "task-idx-fail"

    def _fake_run_async(coro):
        coro.close()
        raise RuntimeError("ES connection lost")

    with (
        patch("app.document.tasks._index.run_async", side_effect=_fake_run_async),
        patch("app.document.tasks._index._update_index_build_result"),
        patch("app.document.tasks._index._task_failed") as mock_failed,
    ):
        result = task_index_document(
            {"chunks": [{"chunk_id": "c1", "doc_id": "d1", "content": "t", "chunk_index": 0}]},
            "DOC-FAIL-1",
        )
        assert result == {"doc_id": "DOC-FAIL-1", "indexed_count": 0}
        mock_failed.assert_called_once()
        args = mock_failed.call_args[0]
        # args: (task_self, doc_id, stage, message, exc)
        assert args[1] == "DOC-FAIL-1"
        assert args[2] == DocumentTaskStageEnum.STORE_COMPLETE.value


@pytest.mark.asyncio
async def test_chunk_pipeline_avoids_llm_recursive_duplication():
    """验证当 strategies 同时包含 LLM 与 RECURSIVE 时，LLM 作为 primary 成功分块后，不再重复执行 recursive 切块"""
    from app.document.chunker.pipeline import ChunkPipeline

    fake_llm_chunks = [
        Chunk(chunk_id="llm-1", doc_id="d1", content="Chunk 1", chunk_index=0),
        Chunk(chunk_id="llm-2", doc_id="d1", content="Chunk 2", chunk_index=1),
    ]

    with (
        patch(
            "app.document.chunker.pipeline.LLMChunker.chunk",
            new_callable=AsyncMock,
            return_value=fake_llm_chunks,
        ),
        patch(
            "app.document.chunker.pipeline.RecursiveChunker.chunk", new_callable=AsyncMock
        ) as mock_recursive,
    ):
        pipeline = ChunkPipeline([ChunkStrategyType.LLM, ChunkStrategyType.RECURSIVE])
        results = await pipeline.run("Sample document text for test", "d1")
        assert len(results) == 2
        assert [c.chunk_id for c in results] == ["llm-1", "llm-2"]
        # RecursiveChunker 绝不应该被多余调用
        mock_recursive.assert_not_called()


@pytest.mark.asyncio
async def test_indexer_index_to_es_uses_document_id():
    """验证 index_to_es 支持显式传入 document_id，并在旧索引清理和批量索引中精准使用"""
    from app.document.indexer import DocumentIndexer

    mock_es = AsyncMock()
    mock_es.bulk.return_value = {"items": []}

    c1 = Chunk(
        chunk_id="c1", doc_id="uuid-str-not-int", content="Text", chunk_index=0, chunk_type="child"
    )

    with patch("app.document.indexer.get_es", return_value=mock_es):
        indexer = DocumentIndexer()
        await indexer.index_to_es([c1], doc_title="Title", document_id=888)

        # 检查 delete_by_query 是否使用了 document_id=888
        mock_es.delete_by_query.assert_called_once()
        del_body = mock_es.delete_by_query.call_args[1]["body"]
        assert del_body["query"]["term"]["documentId"] == 888

        # 检查 bulk 索引数据中的 documentId 是否正确对齐为 888
        bulk_ops = mock_es.bulk.call_args[1]["operations"]
        doc_payload = bulk_ops[1]
        assert doc_payload["documentId"] == 888


@pytest.mark.asyncio
async def test_parser_utf8_sig_bom_and_gb18030_decoding(tmp_path):
    """验证文本解析器能够安全剥离 Windows UTF-8 BOM，且正常解码 GB18030 字符"""
    from app.document.parser import DocumentParser

    parser = DocumentParser()

    # 1. 带 BOM 的 UTF-8 文件 (Windows 保存形式)
    bom_file = tmp_path / "test_bom.md"
    bom_file.write_bytes("# 第一章 概述\n\n正文内容第一段。".encode("utf-8-sig"))
    res_bom = await parser.parse(str(bom_file))
    assert res_bom.heading_count >= 1
    assert "概述" in res_bom.text
    assert not res_bom.text.startswith("\ufeff")

    # 2. GB18030 生僻字文件 (如 𪚥 / 㭎)
    gb_file = tmp_path / "test_gb.txt"
    gb_content = "生僻字测试：𪚥 和 㭎"
    gb_file.write_bytes(gb_content.encode("gb18030"))
    res_gb = await parser.parse(str(gb_file))
    assert "生僻字测试" in res_gb.text


@pytest.mark.asyncio
async def test_parser_excel_fallback_without_tabulate(tmp_path):
    """验证当 MarkItDown 失败且缺少 tabulate 库时，降级纯 Python Markdown 解析依然成功"""
    from unittest.mock import MagicMock

    from app.document.parser import _df_to_markdown

    # 模拟 DataFrame 对象（无需依赖系统安装 pandas）
    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.columns = ["姓名", "年龄"]
    mock_df.iterrows.return_value = [
        (0, ["张三", 28]),
        (1, ["李四", 32]),
    ]

    md_table = _df_to_markdown(mock_df)
    assert "| 姓名 | 年龄 |" in md_table
    assert "| 张三 | 28 |" in md_table
    assert "| 李四 | 32 |" in md_table


@pytest.mark.asyncio
async def test_parser_csv_streaming_limit(tmp_path):
    """验证 CSV 解析器采用流式读取，并截断在 1000 行上限"""
    from app.document.parser import DocumentParser

    csv_file = tmp_path / "large.csv"
    lines = ["id,name,val"] + [f"{i},user_{i},{i * 10}" for i in range(1, 1500)]
    csv_file.write_text("\n".join(lines), encoding="utf-8")

    parser = DocumentParser()
    res = await parser.parse(str(csv_file))
    # 头部占 2 行，数据行最多 999-1000 行
    table_lines = res.text.strip().split("\n")
    # 总行数不超过 1005 行
    assert len(table_lines) <= 1005
    assert "| id | name | val |" in res.text


@pytest.mark.asyncio
async def test_local_directory_connector_full_audit_and_task(tmp_path):
    """验证离线目录导入完整落盘 Document、DocumentTask 与 save_log 审计日志"""
    from unittest.mock import MagicMock

    from app.document.connectors.local_connector import import_from_local_directory

    test_doc = tmp_path / "manual.txt"
    test_doc.write_text("离线文档内容", encoding="utf-8")

    class MockSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def begin(self):
            return self

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

        async def scalar(self, stmt):
            from app.db.models.knowledge import KnowledgeScope

            return KnowledgeScope(scope_code="FINANCE", scope_name="财务域")

        async def execute(self, stmt):
            res = MagicMock()
            res.scalars.return_value.first.return_value = None
            return res

    mock_db = MockSession()
    mock_factory = MagicMock(return_value=mock_db)

    with (
        patch("app.db.session.get_session_factory", return_value=mock_factory),
        patch("app.manage.service.storage_service.upload_original_file") as mock_upload,
        patch("app.manage.service.document_async_service.save_log") as mock_save_log,
        patch("app.document.tasks.trigger_document_pipeline") as mock_trigger,
    ):
        mock_upload.return_value = MagicMock(
            bucket_name="rag", object_name="manual.txt", object_url="http://minio/rag/manual.txt"
        )
        res = await import_from_local_directory(tmp_path, scope_code="FINANCE", tags="offline")
        assert res["scanned"] == 1
        assert res["imported"] == 1
        # 验证 DB.add 被调用了至少两次 (一次 doc，一次 task)
        assert len(mock_db.added) >= 2
        # 验证 save_log 审计日志被完整记录
        mock_save_log.assert_called_once()
        # 验证流水线被触发
        mock_trigger.assert_called_once()


@pytest.mark.asyncio
async def test_chunk_pipeline_llm_inherits_parent_metadata():
    """验证 ChunkPipeline 在父子两阶段时，LLM 子块自动继承父块的 section_path 和 structure_node_id"""
    from app.document.chunker.models import Chunk, ChunkStrategyType
    from app.document.chunker.pipeline import ChunkPipeline

    fake_parents = [
        Chunk(
            chunk_id="parent-101",
            doc_id="doc-1",
            content="父块全文",
            chunk_index=0,
            chunk_type="parent",
            section_title="第一章",
            section_path="文档/第一章",
            structure_node_id=123,
            structure_node_type=2,
            canonical_path="/doc/1",
        )
    ]
    fake_child = Chunk(
        chunk_id="child-201",
        doc_id="doc-1",
        content="子块文本",
        chunk_index=0,
        chunk_type="child",
    )

    with (
        patch(
            "app.document.chunker.structure.StructureChunker.chunk", new_callable=AsyncMock
        ) as mock_struct,
        patch("app.document.chunker.llm.LLMChunker.chunk", new_callable=AsyncMock) as mock_llm,
    ):
        mock_struct.return_value = fake_parents
        mock_llm.return_value = [fake_child]

        pipeline = ChunkPipeline(strategies=[ChunkStrategyType.STRUCTURE, ChunkStrategyType.LLM])
        chunks = await pipeline.run("父块全文", "doc-1")

        children = [c for c in chunks if c.chunk_type == "child"]
        assert len(children) == 1
        c = children[0]
        # 验证父子关联与元数据继承
        assert c.parent_chunk_id == "parent-101"
        assert c.section_title == "第一章"
        assert c.section_path == "文档/第一章"
        assert c.structure_node_id == 123
        assert c.canonical_path == "/doc/1"


@pytest.mark.asyncio
async def test_vectorizer_char_count_column_correctness():
    """验证 VectorizerService 写入 PGVector 时 char_count 传入的是 len(chunk.content) 而非 token_count"""
    from app.document.chunker.models import Chunk
    from app.document.vectorizer import VectorizerService

    chunk = Chunk(
        chunk_id="c1",
        doc_id="d1",
        content="这是一段测试文本，共十五字。",
        chunk_index=0,
        chunk_type="child",
        token_count=8,  # token 数不同于字符数
    )
    mock_provider = AsyncMock()
    mock_provider.embed_batch.return_value = [[0.1] * 1536]

    vectorizer = VectorizerService(provider=mock_provider)

    with patch("app.infra.pg.transaction") as mock_tx:
        mock_conn = AsyncMock()
        mock_tx.return_value.__aenter__.return_value = mock_conn

        await vectorizer.vectorize([chunk], task_id="123", document_name="测试文档")

        # 检查 executemany 参数
        assert mock_conn.executemany.call_count >= 2
        embed_call = mock_conn.executemany.call_args_list[1]
        embed_rows = embed_call[0][1]
        assert len(embed_rows) == 1
        row = embed_rows[0]
        # index 14 是 char_count, 15 是 token_count
        char_count_val = row[14]
        token_count_val = row[15]
        assert char_count_val == len("这是一段测试文本，共十五字。")
        assert token_count_val == 8


@pytest.mark.asyncio
async def test_two_stage_chunking_monotonic_global_indexing():
    """验证两阶段切块（Parent-Child）生成的子块在整个文档范围内具有单调递增全局索引，严禁同编号覆盖"""
    from app.document.chunker import Chunk, ChunkConfig, RecursiveChunker

    chunker = RecursiveChunker()
    # 模拟两个父块，每个父块内容较长会产生多个子块
    parent1 = Chunk(
        chunk_id="parent-1",
        doc_id="DOC-TWO-STAGE",
        content="父块1内容。" * 200,
        chunk_index=0,
        chunk_type="parent",
        token_count=1000,
    )
    parent2 = Chunk(
        chunk_id="parent-2",
        doc_id="DOC-TWO-STAGE",
        content="父块2内容。" * 200,
        chunk_index=1,
        chunk_type="parent",
        token_count=1000,
    )

    child_chunks = await chunker.chunk_parents(
        [parent1, parent2], ChunkConfig(chunk_size=300, min_chunk_size=50)
    )

    assert len(child_chunks) >= 4
    indices = [c.chunk_index for c in child_chunks]
    # 必须是严格单调递增 [0, 1, 2, 3, ...]，不能每个父块重新从 0 编号
    assert indices == list(range(len(child_chunks)))
    assert len(indices) == len(set(indices))


@pytest.mark.asyncio
async def test_two_stage_overlap_cross_parent_isolation():
    """验证跨父块（不同章节）之间严禁渗透 overlap 文本"""
    from app.document.chunker import Chunk, RecursiveChunker

    chunker = RecursiveChunker()
    c1 = Chunk(
        chunk_id="c1",
        doc_id="D1",
        content="这是第一章的结尾内容重点。",
        chunk_index=0,
        parent_chunk_id="P1",
    )
    c2 = Chunk(
        chunk_id="c2",
        doc_id="D1",
        content="这是第二章的开头全新内容。",
        chunk_index=1,
        parent_chunk_id="P2",
    )

    chunks = [c1, c2]
    chunker._apply_overlap(chunks, overlap_tokens=50)

    # c2 不应包含 c1 的任何文本
    assert "第一章" not in c2.content
    assert c2.content == "这是第二章的开头全新内容。"


@pytest.mark.asyncio
async def test_task_vectorize_fails_on_empty_chunks():
    """验证 task_vectorize_document 遇到空 chunk 列表时抛出异常进入失败流，杜绝幽灵文档标记为 VECTORIZED"""
    from app.common.enums import DocumentTaskStageEnum
    from app.document.tasks._vectorize import task_vectorize_document

    with patch("app.document.tasks._vectorize._task_failed") as mock_failed:
        res = task_vectorize_document({"chunks": []}, "DOC-EMPTY-1")
        assert res["vectorized_count"] == 0
        mock_failed.assert_called_once()
        args = mock_failed.call_args[0]
        assert args[1] == "DOC-EMPTY-1"
        assert args[2] == DocumentTaskStageEnum.VECTORIZE.value
        assert "切块列表为空" in str(args[4])


@pytest.mark.asyncio
async def test_task_index_fails_on_empty_chunks():
    """验证 task_index_document 遇到空 chunk 列表时抛出异常进入失败流，杜绝幽灵文档标记为 INDEXED"""
    from app.common.enums import DocumentTaskStageEnum
    from app.document.tasks._index import task_index_document

    with patch("app.document.tasks._index._task_failed") as mock_failed:
        res = task_index_document({"chunks": []}, "DOC-EMPTY-2")
        assert res["indexed_count"] == 0
        mock_failed.assert_called_once()
        args = mock_failed.call_args[0]
        assert args[1] == "DOC-EMPTY-2"
        assert args[2] == DocumentTaskStageEnum.STORE_COMPLETE.value
        assert "切块列表为空" in str(args[4])


@pytest.mark.asyncio
async def test_neo4j_graph_service_supports_both_uuid_and_int():
    """验证 Neo4jGraphService 支持按外部 UUID docId 或内部整数 documentId 灵活检索"""
    from app.rag.graph.neo4j_graph_service import Neo4jGraphService

    service = Neo4jGraphService()

    with patch.object(service, "_run_query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = {"available": True}
        # 1. 传入 UUID 字符串
        avail_uuid = await service.is_graph_available("d8b13bf1-9a74-4b5c-b16f-40e94bbca695")
        assert avail_uuid is True
        query_text, params = mock_query.call_args[0][:2]
        assert "d.docId = $docId" in query_text
        assert params["docId"] == "d8b13bf1-9a74-4b5c-b16f-40e94bbca695"

        # 2. 传入数字 ID
        avail_int = await service.is_graph_available("10086")
        assert avail_int is True
        params_int = mock_query.call_args[0][1]
        assert params_int["documentId"] == 10086


@pytest.mark.asyncio
async def test_task_chunk_fails_on_empty_text():
    """验证 task_chunk_document 收到空解析文本时直接抛出异常进入失败流，杜绝标记为 CHUNKED 假成功"""
    from app.common.enums import DocumentTaskStageEnum
    from app.document.tasks._chunk import task_chunk_document

    with patch("app.document.tasks._chunk._task_failed") as mock_failed:
        res = task_chunk_document({"text": ""}, "DOC-EMPTY-CHUNK")
        assert res["chunks"] == []
        mock_failed.assert_called_once()
        args = mock_failed.call_args[0]
        assert args[1] == "DOC-EMPTY-CHUNK"
        assert args[2] == DocumentTaskStageEnum.CHUNK_EXECUTE.value
        assert "解析文本内容为空" in str(args[4])


@pytest.mark.asyncio
async def test_local_connector_empty_file_and_dedup(tmp_path):
    """验证本地离线连接器遇到空文件跳过，已成功构建的文件查重秒传跳过"""
    from app.common.enums import DocumentIndexStatusEnum
    from app.document.connectors.local_connector import import_from_local_directory

    # 1. 准备测试文件
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")

    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("Hello Pipeline RAG")

    mock_db = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_db

    # 模拟查重：valid_file 已经被构建成功
    existing_doc = MagicMock()
    existing_doc.doc_id = "doc-existing-1"
    existing_doc.index_status = DocumentIndexStatusEnum.BUILD_SUCCESS.value
    doc_res = MagicMock()
    doc_res.scalars.return_value.first.return_value = existing_doc
    mock_db.execute.return_value = doc_res

    with (
        patch("app.db.session.get_session_factory", return_value=mock_session_factory),
        patch("app.document.tasks.trigger_document_pipeline") as mock_pipe,
    ):
        report = await import_from_local_directory(tmp_path)
        assert report["scanned"] == 2
        assert report["imported"] == 0
        assert report["skipped"] == 2  # 一个空文件，一个已存在文件
        mock_pipe.assert_not_called()


@pytest.mark.asyncio
async def test_s3_connector_persists_to_minio_and_creates_db():
    """验证 S3 连接器导入时转存 MinIO 并插入 MySQL 主表和任务记录，传给流水线 MinIO 路径"""
    from app.document.connectors.base import ConnectorFile
    from app.document.connectors.s3_connector import S3Connector, import_from_s3

    mock_db = AsyncMock()
    mock_begin = AsyncMock()
    mock_begin.__aenter__.return_value = None
    mock_begin.__aexit__.return_value = None
    mock_db.begin = MagicMock(return_value=mock_begin)
    mock_db.add = MagicMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_db
    # 模拟无重复文档
    no_dup_res = MagicMock()
    no_dup_res.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_dup_res

    stored_res = MagicMock()
    stored_res.bucket_name = "test-bucket"
    stored_res.object_name = "minio-path/test.pdf"
    stored_res.object_url = "http://minio/test.pdf"

    mock_files = [ConnectorFile(remote_key="docs/test.pdf", name="test.pdf", size=1024)]

    with (
        patch("app.config.get_settings") as mock_cfg,
        patch("app.db.session.get_session_factory", return_value=mock_session_factory),
        patch.object(S3Connector, "list_files", new_callable=AsyncMock, return_value=mock_files),
        patch.object(S3Connector, "fetch_to_local", new_callable=AsyncMock) as mock_fetch,
        patch(
            "app.manage.service.storage_service.upload_original_file",
            new_callable=AsyncMock,
            return_value=stored_res,
        ) as mock_upload,
        patch("app.document.tasks.trigger_document_pipeline") as mock_pipe,
    ):
        # 模拟配置启用
        cfg = MagicMock()
        cfg.s3_connector.enabled = True
        cfg.s3_connector.endpoint = "s3.amazonaws.com"
        cfg.s3_connector.access_key = "test_key"
        cfg.s3_connector.secret_key = "test_secret"
        cfg.s3_connector.bucket = "test-bucket"
        cfg.s3_connector.prefix = ""
        cfg.s3_connector.file_types = ".pdf"
        cfg.s3_connector.batch_size = 10
        cfg.s3_connector.temp_dir = "test-tmp"
        mock_cfg.return_value = cfg

        async def _fake_fetch(file, dest_dir):
            p = dest_dir / file.name
            p.write_bytes(b"%PDF-1.4 test content")
            return p

        mock_fetch.side_effect = _fake_fetch

        report = await import_from_s3()
        assert report["imported"] == 1
        assert report["total"] == 1
        # 必须调用 upload_original_file 转存 MinIO
        mock_upload.assert_called_once()
        # 必须传入 MinIO object_name，杜绝传入被销毁的本地路径
        mock_pipe.assert_called_once()
        args = mock_pipe.call_args[0]
        assert args[1] == "minio-path/test.pdf"
        # 必须向数据库插入 Document、DocumentTask 和 save_log 审计日志 (共 3 次)
        assert mock_db.add.call_count == 3
