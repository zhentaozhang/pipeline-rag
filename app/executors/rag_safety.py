"""Per-chunk streaming safety filter for RAG executor"""

import re

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_SAFETY_PLACEHOLDER = "▊"
_CHUNK_SAFETY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "email", "pii_leak"),
    (
        re.compile(r"(?:sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|pk-[a-zA-Z0-9]{20,})"),
        "api_key",
        "pii_leak",
    ),
    (re.compile(r"\beval\s*\("), "eval()", "code_injection"),
    (re.compile(r"\bexec\s*\("), "exec()", "code_injection"),
    (re.compile(r"\b__import__\s*\("), "__import__()", "code_injection"),
    (re.compile(r"\bcompile\s*\("), "compile()", "code_injection"),
    (re.compile(r"\bos\.system\s*\("), "os.system()", "code_injection"),
    (re.compile(r"\bsubprocess\."), "subprocess.", "code_injection"),
]


def check_chunk_safety(content: str) -> str | None:
    """Per-chunk real-time safety check. Returns block reason or None."""
    for pattern, name, reason in _CHUNK_SAFETY_PATTERNS:
        if pattern.search(content):
            logger.warning("stream_chunk_blocked", pattern=name, reason=reason, chunk=content)
            return reason
    return None
