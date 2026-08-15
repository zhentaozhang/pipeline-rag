

class TestContextualChunking:
    """P0-2：Contextual Chunking——embedding 文本附加文档名与章节路径"""

    def test_build_contextual_text_with_all_parts(self):
        from app.document.chunker import Chunk
        from app.document.vectorizer import VectorizerService

        chunk = Chunk(
            chunk_id="c1",
            doc_id="d1",
            content="此处配置超时时间为 30 秒。",
            chunk_index=0,
            chunk_type="child",
            section_path="安装指南 > 高级配置",
            section_title="高级配置",
        )
        svc = VectorizerService.__new__(VectorizerService)
        text = svc._build_contextual_text(chunk, "系统部署手册")
        assert "系统部署手册" in text
        assert "安装指南 > 高级配置" in text
        assert "此处配置超时时间为 30 秒。" in text

    def test_build_contextual_text_without_section(self):
        from app.document.chunker import Chunk
        from app.document.vectorizer import VectorizerService

        chunk = Chunk(
            chunk_id="c2",
            doc_id="d1",
            content="正文内容。",
            chunk_index=0,
            chunk_type="child",
        )
        svc = VectorizerService.__new__(VectorizerService)
        text = svc._build_contextual_text(chunk, "部署手册")
        assert "部署手册" in text
        assert "正文内容。" in text
        assert "章节" not in text
