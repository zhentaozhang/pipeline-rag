"""`scripts/evaluation/generate_questions.py` 的纯函数与流程测试。"""

from __future__ import annotations

import asyncio

import pytest

from scripts.evaluation.generate_questions import (
    build_generation_messages,
    build_verification_messages,
    build_generated_dataset,
    parse_generation,
    parse_verification,
    question_id,
    question_key,
)


class TestParseGeneration:
    def test_valid(self) -> None:
        out = parse_generation('{"question": "年假几天？", "answer": "五天", "skip": false}')
        assert out == {"question": "年假几天？", "answer": "五天"}

    def test_skip_true(self) -> None:
        assert parse_generation('{"skip": true}') is None

    def test_missing_fields(self) -> None:
        assert parse_generation('{"question": "只有题干"}') is None

    def test_garbage(self) -> None:
        assert parse_generation("我不是 JSON") is None

    def test_markdown_fence_tolerated(self) -> None:
        out = parse_generation('```json\n{"question": "q", "answer": "a"}\n```')
        assert out == {"question": "q", "answer": "a"}


class TestParseVerification:
    def test_pass(self) -> None:
        assert parse_verification('{"pass": true, "reason": "ok"}') is True

    def test_fail(self) -> None:
        assert parse_verification('{"pass": false}') is False

    def test_unparsable_defaults_to_false(self) -> None:
        assert parse_verification("随便说说") is False


class TestQuestionKey:
    def test_whitespace_and_case_ignored(self) -> None:
        assert question_key("年假 有 几天") == question_key("年假有几天")

    def test_different_questions_differ(self) -> None:
        assert question_key("年假几天") != question_key("病假几天")


class TestQuestionId:
    def test_stable(self) -> None:
        assert question_id("42", 0) == question_id("42", 0)

    def test_distinct_per_index(self) -> None:
        assert question_id("42", 0) != question_id("42", 1)


class TestMessages:
    def test_generation_includes_chunk_and_section(self) -> None:
        msgs = build_generation_messages("第五条 年假五天", section_path="第5条 假期")
        assert "第五条 年假五天" in msgs[1]["content"]
        assert "第5条 假期" in msgs[1]["content"]

    def test_verification_includes_candidate(self) -> None:
        msgs = build_verification_messages("原文", "问题？", "答案")
        assert "问题？" in msgs[1]["content"] and "答案" in msgs[1]["content"]


def _chunks() -> list[dict]:
    return [
        {
            "id": 1,
            "chunk_text": "员工每年享有带薪年假 5 天，可跨年顺延。" * 4,
            "section_path": "假期",
            "document_id": 9,
        },
        {
            "id": 2,
            "chunk_text": "出差住宿标准为每晚 600 元，超标部分自理。" * 4,
            "section_path": "报销",
            "document_id": 9,
        },
        {"id": 3, "chunk_text": "太短", "section_path": "", "document_id": 9},
    ]


class TestBuildGeneratedDataset:
    def test_generates_and_filters_duplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        async def fake_chat(client, messages, *, model):
            calls["n"] += 1
            if "质检员" in messages[0]["content"]:
                return '{"pass": true}'
            return '{"question": "年假有几天？", "answer": "5 天"}'

        monkeypatch.setattr("scripts.evaluation.generate_questions._chat", fake_chat)
        out = asyncio.run(build_generated_dataset(_chunks(), per_chunk=2, verify=True))
        # 同一题干只保留一份；短 chunk 被跳过
        assert len(out) == 1
        assert out[0]["relevant_chunk_ids"] == ["1"]
        assert out[0]["category"] == "generated"

    def test_verification_failure_drops_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_chat(client, messages, *, model):
            if "质检员" in messages[0]["content"]:
                return '{"pass": false, "reason": "答案与原文不一致"}'
            return '{"question": "住宿标准多少？", "answer": "600 元"}'

        monkeypatch.setattr("scripts.evaluation.generate_questions._chat", fake_chat)
        out = asyncio.run(build_generated_dataset(_chunks(), per_chunk=1, verify=True))
        assert out == []

    def test_no_verify_keeps_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        counter = {"n": 0}

        async def fake_chat(client, messages, *, model):
            counter["n"] += 1
            return '{"question": "第%d 个问题？", "answer": "600 元"}' % counter["n"]

        monkeypatch.setattr("scripts.evaluation.generate_questions._chat", fake_chat)
        out = asyncio.run(build_generated_dataset(_chunks(), per_chunk=1, verify=False))
        assert len(out) == 2  # chunk 1 与 chunk 2 各一题

    def test_llm_error_is_tolerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_chat(client, messages, *, model):
            raise RuntimeError("boom")

        monkeypatch.setattr("scripts.evaluation.generate_questions._chat", fake_chat)
        out = asyncio.run(build_generated_dataset(_chunks(), per_chunk=1, verify=False))
        assert out == []

    def test_limit_caps_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        async def fake_chat(client, messages, *, model):
            seen.append(messages[1]["content"])
            return '{"question": "q?", "answer": "a"}'

        monkeypatch.setattr("scripts.evaluation.generate_questions._chat", fake_chat)
        asyncio.run(build_generated_dataset(_chunks(), per_chunk=1, verify=False, limit=1))
        assert len(seen) == 1
