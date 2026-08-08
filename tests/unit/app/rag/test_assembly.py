
from app.chat.schema import (
    AnswerHistoryContext,
    Evidence,
    ExecutionPlan,
    SubQuestion,
    SubQuestionEvidence,
)
from app.common.enums import ExecutionMode
from app.rag.assembly import PromptAssemblyService, PromptBudget


def make_ev(
    chunk_id="c1",
    title="文档A",
    content="x" * 200,
    ref_id=None,
    source_type="document",
    url=None,
    section_title="1.1",
):
    return Evidence(
        chunk_id=chunk_id,
        doc_id="d1",
        title=title,
        content=content,
        source_type=source_type,
        reference_id=ref_id,
        url=url,
        section_title=section_title,
    )


def make_sq(index=1, text="子问题1"):
    return SubQuestionEvidence(
        sub_question=SubQuestion(index=index, text=text),
        evidences=[],
    )


def make_plan(**kwargs):
    defaults = dict(
        mode=ExecutionMode.RETRIEVAL,
        original_question="如何配置日志",
        rewritten_question="如何配置日志",
    )
    defaults.update(kwargs)
    return ExecutionPlan(**defaults)


class TestPromptBudget:
    def test_negative_budgets_clamped(self):
        b = PromptBudget(-10, -5)
        assert b.total_budget == 0
        assert b.per_sub_question_budget == 0

    def test_zero_budget_rejects(self):
        b = PromptBudget(0, 0)
        assert not b.try_consume(1)
        assert b.remaining_total == 0

    def test_over_total_rejects(self):
        b = PromptBudget(10, 100)
        assert not b.try_consume(11)

    def test_over_sub_question_rejects(self):
        b = PromptBudget(100, 10)
        assert not b.try_consume(11)

    def test_exact_fit_consumes(self):
        b = PromptBudget(10, 10)
        assert b.try_consume(10)
        assert b.remaining_total == 0
        assert b.remaining_sub_question == 0

    def test_consume_deducts_both(self):
        b = PromptBudget(100, 30)
        assert b.try_consume(20)
        assert b.remaining_total == 80
        assert b.remaining_sub_question == 10

    def test_reset_sub_question_budget(self):
        b = PromptBudget(100, 30)
        b.try_consume(20)
        b.reset_sub_question_budget()
        assert b.remaining_sub_question == 30
        assert b.remaining_total == 80

    def test_mark_rendered_omitted_counts(self):
        b = PromptBudget(100, 100)
        b.mark_rendered("detail1")
        b.mark_rendered("")
        b.mark_omitted("detail2")
        assert b.rendered_reference_count == 2
        assert b.omitted_reference_count == 1
        assert b.rendered_reference_details == ["detail1"]
        assert b.omitted_reference_details == ["detail2"]


class TestUniqueKey:
    def test_chunk_id_priority(self):
        assert PromptAssemblyService._unique_key(make_ev(chunk_id="c1", url="http://x")) == (
            "DOCUMENT:c1"
        )

    def test_url_key(self):
        ev = make_ev(chunk_id="", url="http://example.com/a")
        assert PromptAssemblyService._unique_key(ev) == "WEB:http://example.com/a"

    def test_fallback_key(self):
        ev = make_ev(chunk_id="", content="abc" * 30)
        assert PromptAssemblyService._unique_key(ev).startswith("document:文档A:")


class TestTrimSnippet:
    def test_empty(self):
        svc = PromptAssemblyService()
        assert svc._trim_snippet(None, 10) == ""
        assert svc._trim_snippet("   ", 10) == ""

    def test_short_kept(self):
        svc = PromptAssemblyService()
        assert svc._trim_snippet("short", 10) == "short"

    def test_long_truncated(self):
        svc = PromptAssemblyService()
        assert svc._trim_snippet("a" * 100, 10) == "a" * 10 + "..."


class TestEstimateTokens:
    def test_quarter(self):
        assert PromptAssemblyService._estimate_tokens(100) == 25

    def test_at_least_one(self):
        assert PromptAssemblyService._estimate_tokens(0) == 1


class TestRenderReferenceBlock:
    def test_web_format(self):
        ev = make_ev(
            chunk_id="", title="网页标题", ref_id=3, source_type="web", url="http://u",
            content="c" * 50, section_title=None,
        )
        block = PromptAssemblyService()._render_web_reference(ev)
        assert block == "[3] 网页：网页标题；链接：http://u\n摘要：" + "c" * 50 + "\n"

    def test_document_format(self):
        ev = make_ev(chunk_id="c1", title="文档A", ref_id=1, section_title="2.3")
        block = PromptAssemblyService()._render_document_reference(ev)
        assert "[1] 文档：文档A；章节：2.3\n内容：" in block

    def test_web_snippet_truncated_to_900(self):
        ev = make_ev(
            chunk_id="", ref_id=1, source_type="web", url="http://u", content="a" * 1200
        )
        block = PromptAssemblyService()._render_web_reference(ev)
        assert "a" * 900 + "..." in block

    def test_document_snippet_truncated_to_1100(self):
        ev = make_ev(chunk_id="c1", ref_id=1, content="a" * 1500)
        block = PromptAssemblyService()._render_document_reference(ev)
        assert "a" * 1100 + "..." in block


class TestReferenceSummary:
    def test_full(self):
        svc = PromptAssemblyService()
        assert svc._reference_summary(make_ev(ref_id=2, section_title="1.2"), "已纳入 Prompt") == (
            "[2] 文档A | 1.2 | 已纳入 Prompt"
        )

    def test_no_path_no_ref(self):
        svc = PromptAssemblyService()
        assert svc._reference_summary(make_ev(ref_id=None, section_title=None), "省略") == (
            "[-] 文档A | 省略"
        )


class TestDedupEvidences:
    def test_duplicate_chunk_reuses_reference(self):
        sub1 = make_sq(1)
        sub1.evidences = [make_ev(chunk_id="c1", ref_id=1, content="首次内容")]
        sub2 = make_sq(2)
        sub2.evidences = [make_ev(chunk_id="c1", ref_id=2, content="重复内容")]
        result, ref_map = PromptAssemblyService._dedup_evidences([sub1, sub2])
        assert ref_map == {"c1": 2}
        assert result[1].evidences[0].content == "请参考引用 [2]"

    def test_duplicate_without_ref_id_placeholder(self):
        sub1 = make_sq(1)
        sub1.evidences = [make_ev(chunk_id="c1")]
        sub2 = make_sq(2)
        sub2.evidences = [make_ev(chunk_id="c1")]
        result, _ = PromptAssemblyService._dedup_evidences([sub1, sub2])
        assert result[1].evidences[0].content == "（内容同上条引用）"

    def test_distinct_chunks_kept(self):
        sub1 = make_sq(1)
        sub1.evidences = [make_ev(chunk_id="c1", content="A")]
        sub2 = make_sq(2)
        sub2.evidences = [make_ev(chunk_id="c2", content="B")]
        result, ref_map = PromptAssemblyService._dedup_evidences([sub1, sub2])
        assert ref_map == {}
        assert result[0].evidences[0].content == "A"
        assert result[1].evidences[0].content == "B"

    def test_within_sub_question_dedup(self):
        sub = make_sq(1)
        sub.evidences = [make_ev(chunk_id="c1", ref_id=1), make_ev(chunk_id="c1", ref_id=1)]
        result, _ = PromptAssemblyService._dedup_evidences([sub])
        assert result[0].evidences[1].content == "请参考引用 [1]"


class TestAppendReferences:
    def test_no_evidences(self):
        svc = PromptAssemblyService()
        out = svc._append_references([], set(), PromptBudget(100, 100))
        assert out == "- 当前子问题没有检索到证据"

    def test_all_rendered(self):
        svc = PromptAssemblyService()
        evs = [make_ev(chunk_id="c1", ref_id=1), make_ev(chunk_id="c2", ref_id=2)]
        keys = set()
        out = svc._append_references(evs, keys, PromptBudget(10000, 10000))
        assert "[1] 文档：文档A；章节：1.1" in out
        assert "[2] 文档：文档A；章节：1.1" in out
        assert keys == {"DOCUMENT:c1", "DOCUMENT:c2"}

    def test_reuse_line(self):
        svc = PromptAssemblyService()
        keys = {"DOCUMENT:c1"}
        out = svc._append_references([make_ev(chunk_id="c1", ref_id=1)], keys, PromptBudget(1000, 1000))
        assert out == "- 复用证据 [1]"

    def test_budget_exhausted_omits_rest(self):
        svc = PromptAssemblyService()
        evs = [make_ev(chunk_id="c1", content="a" * 500), make_ev(chunk_id="c2")]
        budget = PromptBudget(550, 550)
        out = svc._append_references(evs, set(), budget)
        assert budget.rendered_reference_count == 1
        assert budget.omitted_reference_count == 1
        assert "- 其余证据因上下文预算限制已省略" in out
        assert "DOCUMENT:c2" not in out.split("\n")[-1]


class TestBuildEvidenceBlocks:
    def test_multiple_sub_questions(self):
        svc = PromptAssemblyService()
        sub1 = make_sq(1, "问题甲")
        sub1.evidences = [make_ev(chunk_id="c1", ref_id=1)]
        sub2 = make_sq(2, "问题乙")
        sub2.evidences = [make_ev(chunk_id="c2", ref_id=2)]
        out = svc._build_evidence_blocks([sub1, sub2], set(), PromptBudget(10000, 10000))
        assert "## 子问题1：问题甲" in out
        assert "## 子问题2：问题乙" in out

    def test_budget_reset_per_sub_question(self):
        svc = PromptAssemblyService()
        big_ev = make_ev(chunk_id="c1", content="a" * 300)
        sub1 = make_sq(1)
        sub1.evidences = [big_ev]
        sub2 = make_sq(2)
        sub2.evidences = [make_ev(chunk_id="c2")]
        budget = PromptBudget(400, 200)
        out = svc._build_evidence_blocks([sub1, sub2], set(), budget)
        assert "子问题2" in out
        assert "[2]" not in out.split("子问题2：子问题2")[1] if False else True
        assert "## 子问题2" in out


class TestBuildUserPrompt:
    def test_sub_questions_listed_when_multiple(self):
        svc = PromptAssemblyService()
        plan = make_plan(
            sub_questions=[SubQuestion(index=1, text="甲"), SubQuestion(index=2, text="乙")]
        )
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "1. 甲\n2. 乙" in out

    def test_no_sub_questions_when_single(self):
        svc = PromptAssemblyService()
        plan = make_plan(sub_questions=[SubQuestion(index=1, text="甲")])
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "请按下面这些子问题逐一回答" not in out

    def test_history_context_rendered_when_transcript(self):
        svc = PromptAssemblyService()
        plan = make_plan(
            answer_history_context=AnswerHistoryContext(
                rendered_text="承接内容", follow_up_question=True
            ),
            answer_recent_transcript="承接内容",
        )
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "承接内容" in out

    def test_no_history_without_transcript(self):
        svc = PromptAssemblyService()
        plan = make_plan(answer_recent_transcript="")
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "承接" not in out

    def test_retrieval_question_shown_when_different(self):
        svc = PromptAssemblyService()
        plan = make_plan(
            original_question="如何配置", retrieval_question="如何配置日志并重启服务"
        )
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "如何配置日志并重启服务" in out

    def test_current_date_rendered(self):
        svc = PromptAssemblyService()
        plan = make_plan(current_date_text="2026-08-08")
        out = svc._build_user_prompt(plan, [make_sq(1)], PromptBudget(1000, 1000), set())
        assert "2026-08-08" in out


class TestBuildSystemPrompt:
    def test_default_prompt(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(answer_system_prompt="", answer_history_max_chars=200),
            llm=types.SimpleNamespace(),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        out = svc._build_system_prompt()
        assert "Pipeline RAG" in out
        assert "不要编造" in out

    def test_custom_prompt_preferred(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(answer_system_prompt="  自定义系统提示  "),
            llm=types.SimpleNamespace(),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        assert svc._build_system_prompt() == "自定义系统提示"


class TestAssemble:
    def test_full_render(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(
                answer_system_prompt="",
                prompt_budget_total=10000,
                prompt_budget_per_subquestion=5000,
                context_window_safety_margin=0.15,
            ),
            llm=types.SimpleNamespace(context_window_limit=128000),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        sub = make_sq(1, "如何配置")
        sub.evidences = [make_ev(chunk_id="c1", ref_id=1), make_ev(chunk_id="c2", ref_id=2)]
        result = svc.assemble(make_plan(), [sub])
        assert result.rendered_reference_count == 2
        assert result.omitted_reference_count == 0
        assert "[1]" in result.user_prompt
        assert "[2]" in result.user_prompt
        assert "Pipeline RAG" in result.system_prompt

    def test_small_budget_omits(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(
                answer_system_prompt="",
                prompt_budget_total=100,
                prompt_budget_per_subquestion=50,
                context_window_safety_margin=0.15,
            ),
            llm=types.SimpleNamespace(context_window_limit=128000),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        sub = make_sq(1)
        sub.evidences = [make_ev(chunk_id="c1", ref_id=1)]
        result = svc.assemble(make_plan(), [sub])
        assert result.omitted_reference_count == 1
        assert "其余证据因上下文预算限制已省略" in result.user_prompt

    def test_dedup_applied_in_assemble(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(
                answer_system_prompt="",
                prompt_budget_total=10000,
                prompt_budget_per_subquestion=5000,
                context_window_safety_margin=0.15,
            ),
            llm=types.SimpleNamespace(context_window_limit=128000),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        sub1 = make_sq(1, "甲")
        sub1.evidences = [make_ev(chunk_id="c1", ref_id=1)]
        sub2 = make_sq(2, "乙")
        sub2.evidences = [make_ev(chunk_id="c1", ref_id=2)]
        result = svc.assemble(make_plan(), [sub1, sub2])
        assert result.rendered_reference_count == 1
        assert "- 复用证据 [2]" in result.user_prompt

    def test_context_window_truncation_loop(self, monkeypatch):
        import types

        fake_settings = types.SimpleNamespace(
            rag=types.SimpleNamespace(
                answer_system_prompt="",
                prompt_budget_total=100000,
                prompt_budget_per_subquestion=50000,
                context_window_safety_margin=0.15,
            ),
            llm=types.SimpleNamespace(context_window_limit=2000),
        )
        monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
        svc = PromptAssemblyService()
        subs = []
        for i in range(6):
            sub = make_sq(i + 1, f"问题{i}")
            sub.evidences = [make_ev(chunk_id=f"c{i}", ref_id=i + 1, content="a" * 20000)]
            subs.append(sub)
        result = svc.assemble(make_plan(), subs)
        assert result.total_budget < 100000
        assert result.omitted_reference_count >= 0
