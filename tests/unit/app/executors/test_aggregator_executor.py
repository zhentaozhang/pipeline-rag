"""AggregatorExecutor 纯逻辑测试：引用去重、拼接、prompt 渲染（无 LLM）。"""

from app.chat.schema import WorkerResult
from app.common.enums import ExecutionMode
from app.executors.aggregator_executor import (
    AggregatorExecutor,
    _merge_references,
    _render_synthesis_prompt,
)


def _result(
    sub_plan_id: str,
    text: str = "",
    refs: list[dict] | None = None,
    error: str | None = None,
) -> WorkerResult:
    return WorkerResult(
        sub_plan_id=sub_plan_id,
        mode=ExecutionMode.RAG_CHAT,
        text=text,
        references=refs or [],
        error=error,
    )


class TestMergeReferences:
    def test_deduplicates_by_id(self):
        results = [
            _result("a", refs=[{"id": "r1", "title": "一"}]),
            _result("b", refs=[{"id": "r1", "title": "一"}, {"id": "r2", "title": "二"}]),
        ]
        merged = _merge_references(results)
        assert [r["id"] for r in merged] == ["r1", "r2"]

    def test_falls_back_to_reference_id_and_title_keys(self):
        results = [
            _result("a", refs=[{"referenceId": "x1"}]),
            _result("b", refs=[{"referenceId": "x1"}, {"title": "t2"}]),
        ]
        merged = _merge_references(results)
        assert len(merged) == 2

    def test_empty_list_returns_empty(self):
        assert _merge_references([]) == []

    def test_preserves_first_occurrence_order(self):
        results = [
            _result("a", refs=[{"id": "r2"}, {"id": "r1"}]),
            _result("b", refs=[{"id": "r1"}]),
        ]
        merged = _merge_references(results)
        assert [r["id"] for r in merged] == ["r2", "r1"]


class TestConcatenate:
    def test_joins_valid_results_with_labels(self):
        results = [
            _result("a", text="结果A"),
            _result("b", text="结果B"),
        ]
        text, refs = AggregatorExecutor._concatenate(results)
        assert "结果A" in text
        assert "结果B" in text
        assert "内部知识库" in text
        assert "结果A" in text and "结果B" in text
        assert text.index("结果A") < text.index("结果B")

    def test_skips_empty_text(self):
        results = [
            _result("a", text="   "),
            _result("b", text="有效内容"),
        ]
        text, _ = AggregatorExecutor._concatenate(results)
        assert "有效内容" in text
        assert "结果A" not in text

    def test_all_empty_returns_empty_text(self):
        text, _ = AggregatorExecutor._concatenate([_result("a", text="")])
        assert text == ""


class TestRenderSynthesisPrompt:
    def test_renders_question_and_results(self):
        prompt = _render_synthesis_prompt(
            "综合问题",
            [_result("a", text="内容A"), _result("b", text="内容B")],
        )
        assert "综合问题" in prompt
        assert "内容A" in prompt
        assert "内容B" in prompt

    def test_empty_results_renders_without_error(self):
        prompt = _render_synthesis_prompt("问题", [])
        assert "问题" in prompt
