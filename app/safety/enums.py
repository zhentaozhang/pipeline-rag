"""
安全检测层枚举
"""

from __future__ import annotations

from enum import StrEnum


def _safety_mode_from_string(
    value: str,
) -> SafetyMode:
    """将字符串转换为 SafetyMode 枚举"""
    mapping = {
        "fail_close": SafetyMode.FAIL_CLOSE,
        "fail_open": SafetyMode.FAIL_OPEN,
        "monitor": SafetyMode.MONITOR,
    }
    return mapping.get(value, SafetyMode.FAIL_CLOSE)


class SafetyMode(StrEnum):
    """安全检测模式"""

    FAIL_CLOSE = "fail_close"
    FAIL_OPEN = "fail_open"
    MONITOR = "monitor"


class ToolRisk(StrEnum):
    """工具风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CircuitState(StrEnum):
    """熔断器状态"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

