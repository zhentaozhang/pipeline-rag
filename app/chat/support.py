"""
Chat 支撑组件
"""

from dataclasses import dataclass


@dataclass
class StreamEventMetadata:
    """流事件元数据"""

    conversation_id: str = ""
    exchange_id: int | None = None


def resolve_provider(base_url: str | None) -> str:
    """探测 LLM provider 类型"""
    if not base_url or not base_url.strip():
        return "unknown"
    normalized = base_url.strip().lower()
    if "siliconflow" in normalized:
        return "siliconflow"
    if "dashscope" in normalized or "aliyuncs" in normalized:
        return "dashscope"
    return normalized


def is_dashscope_provider(provider: str) -> bool:
    return provider == "dashscope"
