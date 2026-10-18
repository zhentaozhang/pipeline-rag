"""P0-1 真 Contextual Retrieval：向量化文本构造的纯逻辑测试（无网络）。"""

import types

from app.config import get_settings
from app.document.vectorizer import VectorizerService


def make_chunk(cid, content, ctype="child", path="", title=""):
    return types.SimpleNamespace(
        chunk_id=cid, content=content, chunk_type=ctype, section_path=path, section_title=title
    )


class TestComposeDocumentText:
    def test_prefers_parent_chunks(self):
        chunks = [
            make_chunk("p1", "甲甲甲", "parent"),
            make_chunk("c1", "乙乙乙", "child"),
            make_chunk("p2", "丙丙丙", "parent"),
        ]
        text = VectorizerService._compose_document_text(chunks)
        assert "甲甲甲" in text and "丙丙丙" in text and "乙乙乙" not in text

    def test_fallback_to_all_when_no_parent(self):
        chunks = [make_chunk("c1", "乙"), make_chunk("c2", "丁")]
        assert VectorizerService._compose_document_text(chunks) == "乙\n\n丁"

    def test_truncates_to_limit(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "contextual_llm_max_doc_chars", 5)
        chunks = [make_chunk("p1", "abcdefghij", "parent")]
        assert VectorizerService._compose_document_text(chunks) == "abcde"


class TestBuildContextualText:
    def test_llm_context_prepended(self):
        c = make_chunk("c1", "正文内容", path="第一章")
        out = VectorizerService._build_contextual_text(c, "员工手册", "该片段规定了考勤。")
        assert out.startswith("该片段规定了考勤。")
        assert "文档：《员工手册》" in out
        assert "章节：第一章" in out
        assert out.rstrip().endswith("正文内容")

    def test_without_llm_context_falls_back(self):
        c = make_chunk("c1", "正文内容", path="第一章")
        out = VectorizerService._build_contextual_text(c, "员工手册")
        assert "该片段" not in out
        assert "文档：《员工手册》" in out


class TestConfigDefaults:
    def test_contextual_llm_default_off(self):
        # 默认关闭 → 现状行为不变（零风险）
        assert get_settings().rag.contextual_llm_enabled is False


class TestContextualBm25Plumbing:
    def test_chunk_default_context_empty_and_serializable(self):
        from dataclasses import asdict

        from app.document.chunker.models import Chunk

        c = Chunk(chunk_id="c1", doc_id="d1", content="正文", chunk_index=0)
        assert c.contextual_context == ""
        # 可经 asdict 序列化，从而在 Celery 任务间传递
        assert asdict(c)["contextual_context"] == ""

    def test_index_text_prepends_context(self):
        from app.document.chunker.models import Chunk
        from app.document.indexer import DocumentIndexer

        c = Chunk(
            chunk_id="c1",
            doc_id="d1",
            content="正文",
            chunk_index=0,
            contextual_context="该片段规定了考勤。",
        )
        out = DocumentIndexer._compose_index_text(c)
        assert out.startswith("该片段规定了考勤。")
        assert out.endswith("正文")

    def test_index_text_unchanged_without_context(self):
        from app.document.chunker.models import Chunk
        from app.document.indexer import DocumentIndexer

        c = Chunk(chunk_id="c1", doc_id="d1", content="正文", chunk_index=0)
        assert DocumentIndexer._compose_index_text(c) == "正文"
