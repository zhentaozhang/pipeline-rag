import json
import re
import types

import pytest

from app.document.structure.pipeline import DocumentStructurePipeline


def _resolve_ambiguous_as_body(kwargs):
    """确定性歧义消解：把所有候选行判为 BODY（正文）。

    pipeline 的歧义消解阶段会调 LLM，真调会因模型波动导致结构不稳定（flaky）。
    这里从 prompt 中解析候选行号（structure_parse_candidate.j2 模板用 `### 候选行 N`），
    统一判为 BODY —— 即“普通正文行不应成为 section”这一被测意图。
    """
    prompt = kwargs["messages"][-1]["content"]
    line_nos = re.findall(r"候选行\s+(\d+)", prompt)
    return json.dumps(
        [{"line_no": int(n), "resolved_kind": "BODY"} for n in line_nos], ensure_ascii=False
    )


@pytest.fixture
def pipeline(fake_llm):
    fake_llm.set_fallback(_resolve_ambiguous_as_body)
    return DocumentStructurePipeline()


class TestEmptyInput:
    async def test_empty_text_returns_document_node(self, pipeline):
        candidates = await pipeline.extract("文档", "")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.node_no == 1
        assert c.node_type == "document"
        assert c.parent_node_no is None
        assert c.canonical_path == "/document"
        assert c.title == "文档"
        assert c.anchor_text == "文档"
        assert c.content_text == ""

    async def test_none_inputs(self, pipeline):
        candidates = await pipeline.extract(None, None)
        assert len(candidates) == 1
        assert candidates[0].title == "文档"

    async def test_blank_text_keeps_title(self, pipeline):
        candidates = await pipeline.extract(" 我的文档 ", "  ")
        assert len(candidates) == 1
        assert candidates[0].title == "我的文档"


class TestStageWiring:
    async def test_five_stage_chain(self, pipeline):
        calls = []

        class FakeExtractor:
            def extract(self, title, text):
                calls.append(("extract", title, text))
                return types.SimpleNamespace(context_lines=("ctx",), signals=("sig", text))

        class FakeResolver:
            async def resolve(self, title, context_lines, signals):
                calls.append(("ambiguity", title, context_lines, signals))
                return ("resolved_signals",)

        class FakeHierarchy:
            def resolve(self, title, resolved_signals):
                calls.append(("hierarchy", title, resolved_signals))
                return ("drafts",)

        class FakeValidator:
            def validate_and_build(self, title, drafts):
                calls.append(("validate", title, drafts))
                return "candidates"

        pipeline.signal_extractor = FakeExtractor()
        pipeline.ambiguity_resolver = FakeResolver()
        pipeline.hierarchy_resolver = FakeHierarchy()
        pipeline.tree_validator = FakeValidator()

        result = await pipeline.extract("标题", "正文内容")
        assert result == "candidates"
        assert calls == [
            ("extract", "标题", "正文内容"),
            ("ambiguity", "标题", ("ctx",), ("sig", "正文内容")),
            ("hierarchy", "标题", ("resolved_signals",)),
            ("validate", "标题", ("drafts",)),
        ]


class TestEndToEnd:
    async def test_markdown_document_builds_tree(self, pipeline):
        text = "# 第一章 概述\n这是正文内容\n\n## 1.1 背景\n详细说明"
        candidates = await pipeline.extract("测试文档", text)
        by_no = {c.node_no: c for c in candidates}
        assert len(candidates) >= 2
        assert by_no[1].node_type == "document"
        sections = [c for c in candidates if c.node_type == "section"]
        assert len(sections) == 2
        first, second = sorted(sections, key=lambda c: c.node_no)
        assert first.title == "第一章 概述"
        assert second.parent_node_no == first.node_no
        assert second.depth == first.depth + 1

    async def test_step_list_creates_items(self, pipeline):
        text = "第1步：初始化。\n第2步：配置。"
        candidates = await pipeline.extract("流程文档", text)
        kinds = [c.node_type for c in candidates]
        assert "step" in kinds
