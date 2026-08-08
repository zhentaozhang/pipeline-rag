import types

import pytest

from app.document.structure.ambiguity import DocumentStructureAmbiguityResolver
from app.document.structure.models import (
    DocumentStructureSignal,
    DocumentStructureSignalKind,
)


def amb_sig(line_no, confidence=0.6, title="疑似标题", kind=None, node_code=""):
    return DocumentStructureSignal(
        line_no=line_no,
        raw_text=f"行{line_no}内容",
        normalized_text=f"行{line_no}内容",
        kind=kind or DocumentStructureSignalKind.HEADING_CANDIDATE,
        node_code=node_code,
        title=title,
        confidence=confidence,
    )


def clear_sig(line_no):
    return DocumentStructureSignal(
        line_no=line_no,
        raw_text="正文",
        normalized_text="正文",
        kind=DocumentStructureSignalKind.BODY,
    )


def make_properties(**overrides):
    defaults = dict(
        llm_disambiguation_enabled=True,
        ambiguity_confidence_floor=0.45,
        ambiguity_confidence_ceil=0.80,
        max_ambiguous_signals_per_call=8,
        context_window_lines=2,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class FakeCompletions:
    def __init__(self, content):
        self.content = content

    async def create(self, **kwargs):
        resp = types.SimpleNamespace()
        resp.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=self.content))]
        return resp


class FakeClient:
    def __init__(self, content=None, error=None, base_url=None):
        self.content = content
        self.error = error
        self.base_url = base_url or "https://api.openai.com"
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return await FakeCompletions(self.content).create(**kwargs)


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(
        "app.document.structure.ambiguity.get_chat_client",
        lambda: FakeClient(content="[]"),
    )
    monkeypatch.setattr(
        "app.document.structure.ambiguity.get_settings",
        lambda: types.SimpleNamespace(
            structure=make_properties(), llm=types.SimpleNamespace(model="gpt-test")
        ),
    )
    return DocumentStructureAmbiguityResolver()


class TestResolve:
    @pytest.mark.asyncio
    async def test_empty_signals(self, resolver):
        assert await resolver.resolve("文档", [], []) == []

    @pytest.mark.asyncio
    async def test_disabled_returns_as_is(self, resolver):
        resolver.properties = make_properties(llm_disambiguation_enabled=False)
        signals = [amb_sig(1)]
        assert await resolver.resolve("文档", [], signals) == signals

    @pytest.mark.asyncio
    async def test_no_ambiguous_signals(self, resolver):
        signals = [clear_sig(1), clear_sig(2)]
        assert await resolver.resolve("文档", [], signals) == signals

    @pytest.mark.asyncio
    async def test_confidence_filtered(self, resolver):
        resolver.properties = make_properties(ambiguity_confidence_floor=0.5, ambiguity_confidence_ceil=0.7)
        low = amb_sig(1, confidence=0.3)
        mid = amb_sig(2, confidence=0.6)
        high = amb_sig(3, confidence=0.9)
        signals = [low, mid, high]
        resolver._openai.content = '[{"line_no": 2, "resolved_kind": "HEADING"}]'
        out = await resolver.resolve("文档", [], signals)
        assert out == signals

    @pytest.mark.asyncio
    async def test_max_ambiguous_capped(self, resolver):
        resolver.properties = make_properties(max_ambiguous_signals_per_call=2)
        signals = [amb_sig(i) for i in range(1, 6)]
        resolver._openai.content = "[]"
        await resolver.resolve("文档", [], signals)
        assert len(resolver._openai.calls) == 1

    @pytest.mark.asyncio
    async def test_result_applied(self, resolver):
        signals = [amb_sig(2)]
        resolver._openai.content = '[{"line_no": 2, "resolved_kind": "HEADING", "level_hint": 3}]'
        out = await resolver.resolve("文档", [], signals)
        assert out[0].kind == DocumentStructureSignalKind.HEADING
        assert out[0].level_hint == 3
        assert out[0].reasons[-1] == "llm-disambiguated"
        assert out[0].confidence >= 0.88

    @pytest.mark.asyncio
    async def test_list_item_result(self, resolver):
        signals = [amb_sig(1)]
        resolver._openai.content = '[{"line_no": 1, "resolved_kind": "LIST_ITEM"}]'
        out = await resolver.resolve("文档", [], signals)
        assert out[0].kind == DocumentStructureSignalKind.LIST_ITEM

    @pytest.mark.asyncio
    async def test_empty_result_returns_as_is(self, resolver):
        signals = [amb_sig(1)]
        resolver._openai.content = "[]"
        assert await resolver.resolve("文档", [], signals) == signals

    @pytest.mark.asyncio
    async def test_llm_error_falls_back(self, resolver):
        signals = [amb_sig(1)]
        resolver._openai.error = RuntimeError("llm down")
        assert await resolver.resolve("文档", [], signals) == signals

    @pytest.mark.asyncio
    async def test_prompt_built_with_template(self, resolver):
        signals = [amb_sig(1)]
        resolver._openai.content = "[]"
        await resolver.resolve("文档标题", [], signals)
        prompt = resolver._openai.calls[0]["messages"][0]["content"]
        assert "文档标题" in prompt

    @pytest.mark.asyncio
    async def test_unmatched_line_no_unchanged(self, resolver):
        signals = [amb_sig(1)]
        resolver._openai.content = '[{"line_no": 99, "resolved_kind": "HEADING"}]'
        out = await resolver.resolve("文档", [], signals)
        assert out[0].kind == DocumentStructureSignalKind.HEADING_CANDIDATE


class TestBuildCandidateBlocks:
    def test_context_window_lines(self, resolver):
        resolver.properties = make_properties(context_window_lines=1)
        all_lines = [f"L{i}" for i in range(1, 10)]
        out = resolver._build_candidate_blocks([amb_sig(5, title="标题五")], all_lines)
        assert ">> 5: L5" in out
        assert "4: L4" in out
        assert "6: L6" in out
        assert "7: L7" not in out

    def test_current_line_marker(self, resolver):
        resolver.properties = make_properties(context_window_lines=2)
        all_lines = ["a", "b", "c", "d", "e"]
        out = resolver._build_candidate_blocks([amb_sig(3, title="标题三")], all_lines)
        assert ">> 3: c" in out
        assert out.count(">>") == 1

    def test_window_clamped_at_bounds(self, resolver):
        resolver.properties = make_properties(context_window_lines=2)
        all_lines = ["a", "b", "c", "d", "e"]
        out = resolver._build_candidate_blocks([amb_sig(1, title="首行")], all_lines)
        assert "1: a" in out
        assert "4: d" not in out

    def test_blocks_joined(self, resolver):
        resolver.properties = make_properties(context_window_lines=0)
        all_lines = ["a", "b"]
        out = resolver._build_candidate_blocks([amb_sig(1, title="一"), amb_sig(2, title="二")], all_lines)
        assert "候选行 1" in out
        assert "候选行 2" in out

    def test_empty_lines_safe(self, resolver):
        resolver.properties = make_properties(context_window_lines=2)
        out = resolver._build_candidate_blocks([amb_sig(1, title="一")], None)
        assert "候选行 1" in out

    def test_line_out_of_range_safe(self, resolver):
        resolver.properties = make_properties(context_window_lines=2)
        out = resolver._build_candidate_blocks([amb_sig(99, title="越界")], ["a"])
        assert "候选行 99" in out

    def test_initial_fields_rendered(self, resolver):
        resolver.properties = make_properties(context_window_lines=0)
        out = resolver._build_candidate_blocks(
            [amb_sig(1, title="疑似标题", node_code="1.1")], ["x"]
        )
        assert "初始判断：HEADING_CANDIDATE" in out
        assert "初始标题：疑似标题" in out
        assert "初始编码：1.1" in out


class TestParseJsonResult:
    def test_valid_array(self, resolver):
        assert resolver._parse_json_result('[{"line_no": 1}]') == [{"line_no": 1}]

    def test_empty_content(self, resolver):
        assert resolver._parse_json_result("") == []
        assert resolver._parse_json_result(None) == []

    def test_no_brackets(self, resolver):
        assert resolver._parse_json_result("no json here") == []

    def test_reversed_brackets(self, resolver):
        assert resolver._parse_json_result("]not json[") == []

    def test_invalid_json(self, resolver):
        assert resolver._parse_json_result("[{broken]") == []

    def test_extracts_array_from_wrapped_text(self, resolver):
        content = '```json\n[{"line_no": 1, "resolved_kind": "HEADING"}]\n```'
        assert resolver._parse_json_result(content) == [{"line_no": 1, "resolved_kind": "HEADING"}]

    def test_trailing_text_after_array(self, resolver):
        content = '[{"a": 1}] 后面还有解释'
        assert resolver._parse_json_result(content) == [{"a": 1}]


class TestApplyResult:
    def test_none_returns_source(self, resolver):
        s = amb_sig(1)
        assert resolver._apply_result(s, None) is s

    def test_no_resolved_kind(self, resolver):
        s = amb_sig(1)
        assert resolver._apply_result(s, {"line_no": 1}) is s

    def test_heading_mapping(self, resolver):
        s = amb_sig(1)
        out = resolver._apply_result(s, {"resolved_kind": "HEADING", "level_hint": 2})
        assert out.kind == DocumentStructureSignalKind.HEADING
        assert out.level_hint == 2

    def test_list_item_mapping(self, resolver):
        s = amb_sig(1)
        out = resolver._apply_result(s, {"resolved_kind": "LIST_ITEM"})
        assert out.kind == DocumentStructureSignalKind.LIST_ITEM

    def test_unknown_kind_becomes_body(self, resolver):
        s = amb_sig(1)
        out = resolver._apply_result(s, {"resolved_kind": "TABLE"})
        assert out.kind == DocumentStructureSignalKind.BODY

    def test_case_insensitive_kind(self, resolver):
        s = amb_sig(1)
        out = resolver._apply_result(s, {"resolved_kind": "heading"})
        assert out.kind == DocumentStructureSignalKind.HEADING

    def test_bad_level_hint_ignored(self, resolver):
        s = amb_sig(1)
        out = resolver._apply_result(s, {"resolved_kind": "HEADING", "level_hint": 0})
        assert out.level_hint is None
        out = resolver._apply_result(s, {"resolved_kind": "HEADING", "level_hint": "3"})
        assert out.level_hint is None

    def test_reasons_and_confidence(self, resolver):
        s = amb_sig(1, confidence=0.5)
        out = resolver._apply_result(s, {"resolved_kind": "BODY"})
        assert out.reasons == ["llm-disambiguated"]
        assert out.confidence == 0.88

    def test_confidence_not_lowered(self, resolver):
        s = amb_sig(1, confidence=0.95)
        out = resolver._apply_result(s, {"resolved_kind": "BODY"})
        assert out.confidence == 0.95
