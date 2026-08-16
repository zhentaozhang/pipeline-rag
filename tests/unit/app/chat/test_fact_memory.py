"""P3 · 用户事实记忆（Mem0 式）：抽取解析 / 去重 / 注入渲染"""

from types import SimpleNamespace

from app.chat.fact_memory import parse_extraction_response
from app.rag.assembly import PromptAssemblyService


def test_parse_extraction_response_json():
    raw = '[{"content": "用户是后端工程师", "category": "identity"}, {"content": "用户偏好简洁回答", "category": "preference"}]'
    facts = parse_extraction_response(raw)
    assert len(facts) == 2
    assert facts[0].content == "用户是后端工程师"
    assert facts[0].category == "identity"


def test_parse_with_code_fence():
    raw = '```json\\n[{"content": "用户喜欢 Python", "category": "preference"}]\\n```'
    facts = parse_extraction_response(raw)
    assert len(facts) == 1
    assert facts[0].category == "preference"


def test_parse_empty_and_noise():
    assert parse_extraction_response("") == []
    assert parse_extraction_response("没有任何可记忆信息") == []
    assert parse_extraction_response("[]") == []
    assert parse_extraction_response("not json at all") == []


def test_parse_filters_short_and_invalid():
    raw = '[{"content": "x", "category": "fact"}, {"content": "用户是测试工程师", "category": "unknown"}, "not-dict"]'
    facts = parse_extraction_response(raw)
    # "x" 太短过滤；unknown → fact；字符串元素忽略
    assert len(facts) == 1
    assert facts[0].content == "用户是测试工程师"
    assert facts[0].category == "fact"  # 非法 category 归一为 fact


def test_system_prompt_includes_user_memory(monkeypatch):
    import types

    fake_settings = types.SimpleNamespace(
        rag=types.SimpleNamespace(answer_system_prompt="", answer_history_max_chars=200),
        llm=types.SimpleNamespace(),
    )
    monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
    svc = PromptAssemblyService()
    plan = SimpleNamespace(
        user_memory_context=["用户是后端工程师", "用户偏好简洁回答"]
    )
    out = svc._build_system_prompt(plan)
    assert "用户是后端工程师" in out
    assert "跨轮记忆" in out


def test_system_prompt_without_memory_unchanged(monkeypatch):
    import types

    fake_settings = types.SimpleNamespace(
        rag=types.SimpleNamespace(answer_system_prompt="", answer_history_max_chars=200),
        llm=types.SimpleNamespace(),
    )
    monkeypatch.setattr("app.rag.assembly.settings", fake_settings)
    svc = PromptAssemblyService()
    out = svc._build_system_prompt(SimpleNamespace(user_memory_context=[]))
    assert "跨轮记忆" not in out


def test_retrieve_disabled_default(monkeypatch):
    """默认关闭：execute_stream 不检索（配置 enabled=False 时 getattr 安全返回）"""
    from app.config import get_settings

    assert get_settings().fact_memory.enabled is False
