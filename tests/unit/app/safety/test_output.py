import pytest

import app.safety.output as output_module
from app.safety.output import OutputFilter, SafetyResponse


def make_settings(mode="monitor"):
    return type("S", (), {"mode": mode})()


@pytest.fixture(autouse=True)
def reset_presidio():
    OutputFilter._PRESIDIO_CHECK = None


class TestPiiPatterns:
    @pytest.mark.asyncio
    async def test_phone(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("请联系 13812345678 咨询")
        assert result.safe is False
        assert "phone" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_id_card(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("身份证号 110101199003077712")
        assert result.safe is False
        assert "id_card" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_email(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("联系 admin@example.com 获取")
        assert result.safe is False
        assert "email" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_api_key(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("密钥 sk-abcdefghijklmnopqrstuvwxyz123456")
        assert result.safe is False
        assert "api_key" in result.reason.lower()


class TestSystemPromptLeak:
    @pytest.mark.asyncio
    async def test_two_markers_blocked(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        text = "你的任务是回答用户问题。作为AI，你必须遵守规范。"
        result = await f.filter(text)
        assert result.safe is False
        assert result.reason == "system_prompt_leak"

    @pytest.mark.asyncio
    async def test_single_marker_passes(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("你的任务是回答用户问题。")
        assert result.safe is True


class TestCodeInjection:
    @pytest.mark.asyncio
    async def test_eval_blocked(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("执行 eval(data)")
        assert result.safe is False
        assert result.reason == "code_injection"

    @pytest.mark.asyncio
    async def test_os_system_blocked(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("调用 os.system('rm -rf /')")
        assert result.safe is False

    @pytest.mark.asyncio
    async def test_safe_code_passes(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        result = await f.filter("def add(a, b): return a + b")
        assert result.safe is True


class TestPresidioPath:
    @pytest.mark.asyncio
    async def test_presidio_hit_takes_priority(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        monkeypatch.setattr(
            "app.safety.presidio_pii.check_output_pii", lambda text: "PRESIDIO_PII"
        )
        f = OutputFilter()
        result = await f.filter("正常文本 13812345678")
        assert result.safe is False
        assert result.reason == "pii_leak:PRESIDIO_PII"

    @pytest.mark.asyncio
    async def test_presidio_none_falls_to_regex(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        monkeypatch.setattr(
            "app.safety.presidio_pii.check_output_pii", lambda text: None
        )
        f = OutputFilter()
        result = await f.filter("邮箱 a@b.com")
        assert result.safe is False
        assert "email" in result.reason


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_fail_close_blocks(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings("fail_close")
        )
        f = OutputFilter()
        result = await f.filter("whatever")
        f._check_pii_leak = lambda text: (_ for _ in ()).throw(RuntimeError("boom"))
        result = await f.filter("whatever")
        assert result.safe is False
        assert "output_filter_error" in result.reason

    @pytest.mark.asyncio
    async def test_monitor_passes(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings("monitor")
        )
        f = OutputFilter()
        f._check_pii_leak = lambda text: (_ for _ in ()).throw(RuntimeError("boom"))
        result = await f.filter("whatever")
        assert result.safe is True


class TestBlankText:
    @pytest.mark.asyncio
    async def test_empty_passes(self, monkeypatch):
        monkeypatch.setattr(
            output_module, "get_safety_settings", lambda: make_settings()
        )
        f = OutputFilter()
        assert (await f.filter("   ")).safe is True
        assert (await f.filter("")).safe is True


class TestSafetyResponse:
    def test_pii_template(self):
        msg = SafetyResponse.get_block_message("pii_leak:phone")
        assert "敏感信息" in msg

    def test_system_prompt_template(self):
        msg = SafetyResponse.get_block_message("system_prompt_leak")
        assert "不符合规范" in msg

    def test_unknown_falls_back(self):
        msg = SafetyResponse.get_block_message("something_else")
        assert "不符合安全规范" in msg

    def test_prefix_match_priority(self):
        assert SafetyResponse.get_block_message("output_filter_error: boom") == SafetyResponse.OUTPUT_BLOCK_TEMPLATES["output_filter_error"]
