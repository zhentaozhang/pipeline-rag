"""P1-3 元数据预过滤：解析器 + 请求工厂下发（纯逻辑，无 DB / 无网络）。"""

import pytest

from app.chat.schema import ExecutionPlan, SubQuestion
from app.common.enums import ExecutionMode
from app.config import get_settings
from app.rag import metadata_filter
from app.rag.metadata_filter import (
    clear_cache,
    resolve_first_section_prefix,
    resolve_section_prefix,
)
from app.rag.retrieve_request_factory import DocumentRetrieveRequestFactory


def _plan_with(subs):
    plan = ExecutionPlan(
        mode=ExecutionMode.RAG_CHAT, original_question="原始", rewritten_question="改写"
    )
    plan.sub_questions = subs
    return plan


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


class TestResolveSectionPrefix:
    async def test_hit_returns_hint(self, monkeypatch):
        captured = {}

        async def fake_fetch(sql, *args):
            captured["args"] = args
            return [{"section_path": "第8条 请假类型与审批权限 > **8.1 事假**"}]

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        assert await resolve_section_prefix("第8条") == "第8条"
        assert captured["args"][0] == "第8条%"

    async def test_miss_returns_none(self, monkeypatch):
        async def fake_fetch(sql, *args):
            return []

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        assert await resolve_section_prefix("第99条") is None

    async def test_error_fails_open(self, monkeypatch):
        async def fake_fetch(sql, *args):
            raise RuntimeError("db down")

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        assert await resolve_section_prefix("第8条") is None

    async def test_empty_hint(self):
        assert await resolve_section_prefix("   ") is None

    async def test_cached_second_call_no_query(self, monkeypatch):
        calls = {"n": 0}

        async def fake_fetch(sql, *args):
            calls["n"] += 1
            return [{"section_path": "第8条 ..."}]

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        await resolve_section_prefix("第8条")
        await resolve_section_prefix("第8条")
        assert calls["n"] == 1

    async def test_resolve_first_skips_miss(self, monkeypatch):
        async def fake_fetch(sql, *args):
            return [{"section_path": "附录A 部署"}] if args[0].startswith("附录A") else []

        monkeypatch.setattr("app.infra.pg.fetch", fake_fetch)
        assert await resolve_first_section_prefix(["第99条", "附录A"]) == "附录A"


class TestFactoryWiring:
    async def test_disabled_keeps_section_path_unset(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "metadata_prefilter_enabled", False)
        sub = SubQuestion(index=0, text="第8条 事假怎么申请")
        await DocumentRetrieveRequestFactory().build(_plan_with([sub]))
        assert sub.section_path is None
        # 提示本身仍应被记录（此前被丢弃）
        assert sub.section_path_hints == ["第8条"]

    async def test_enabled_and_resolved_sets_filter(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "metadata_prefilter_enabled", True)

        async def fake_resolve(hints):
            return "第8条"

        monkeypatch.setattr("app.rag.metadata_filter.resolve_first_section_prefix", fake_resolve)
        sub = SubQuestion(index=0, text="第8条 事假怎么申请")
        await DocumentRetrieveRequestFactory().build(_plan_with([sub]))
        assert sub.section_path == "第8条"

    async def test_enabled_but_unresolved_fails_open(self, monkeypatch):
        monkeypatch.setattr(get_settings().rag, "metadata_prefilter_enabled", True)

        async def fake_resolve(hints):
            return None

        monkeypatch.setattr("app.rag.metadata_filter.resolve_first_section_prefix", fake_resolve)
        sub = SubQuestion(index=0, text="第8条 事假怎么申请")
        await DocumentRetrieveRequestFactory().build(_plan_with([sub]))
        assert sub.section_path is None


class TestConfigDefault:
    def test_prefilter_default_off(self):
        assert get_settings().rag.metadata_prefilter_enabled is False


def test_module_importable():
    assert metadata_filter is not None
