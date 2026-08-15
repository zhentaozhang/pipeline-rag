"""
安全检测层配置
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.safety.enums import SafetyMode

_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")


class SafetySettings(BaseSettings):
    """安全检测层全局配置"""

    mode: SafetyMode = SafetyMode.FAIL_CLOSE

    # L1 输入检测
    input_pii_enabled: bool = True
    input_injection_enabled: bool = True
    input_injection_threshold: float = 7.0
    # P0-1a: LLM 深度意图护栏（规则通道已含注入检测/PII，LLM 通道仅作兜底，默认关闭以减 LLM 调用）
    input_llm_guardrail_enabled: bool = False

    # L3 输出检测
    output_pii_enabled: bool = True
    output_sensitive_enabled: bool = True

    # L2 工具准入
    tool_approval_enabled: bool = True

    model_config = SettingsConfigDict(env_prefix="SAFETY_", env_file=_ENV_FILE, extra="ignore")


@lru_cache
def get_safety_settings() -> SafetySettings:
    return SafetySettings()


class CircuitBreakerSettings(BaseSettings):
    """熔断器全局配置"""

    enabled: bool = True
    llm_failure_threshold: int = 5
    llm_recovery_timeout: int = 60
    default_timeout: int = 30

    model_config = SettingsConfigDict(env_prefix="CB_", env_file=_ENV_FILE, extra="ignore")
