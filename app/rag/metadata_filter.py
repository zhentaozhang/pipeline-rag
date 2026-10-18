"""P1-3 元数据预过滤：把"章节提示"经存在性校验后落为真实的 section_path 前缀过滤。

背景（存在 ≠ 能力）：``DocumentRetrieveRequestFactory._build_filters`` 早已抽出
``section_path_hints``（如"第8条/附录A"），但既不下发到 SubQuestion、也没有任何通道消费，
因此元数据过滤维度长期是"死"的。

设计原则（安全第一）：
- 默认关（``settings.rag.metadata_prefilter_enabled``）；
- 任何提示都必须先在语料里"验证存在"，否则原样跳过 → 过滤永不制造零召回；
- 任何异常 → 返回 None（fail-open），绝不阻断检索；
- 命中结果带 TTL 缓存，避免每轮查询都打库。
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)

# hint -> (expire_monotonic, resolved_hint | None)
_cache: dict[str, tuple[float, str | None]] = {}


def _cache_ttl(ttl_seconds: float | None = None) -> float:
    if ttl_seconds is not None:
        return ttl_seconds
    from app.config import get_settings

    return float(
        getattr(get_settings().rag, "metadata_prefilter_cache_ttl_seconds", 300.0) or 300.0
    )


def clear_cache() -> None:
    """清空解析缓存（测试 / 语料重建后使用）。"""
    _cache.clear()


async def resolve_section_prefix(hint: str, ttl_seconds: float | None = None) -> str | None:
    """在语料中查找以该提示开头的 section_path。

    命中返回**原始提示**（可直接作为 ``section_path LIKE hint||'%'`` 的过滤值）；
    未命中或异常返回 None。
    """
    key = (hint or "").strip()
    if not key:
        return None

    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    resolved: str | None = None
    try:
        from app.infra.pg import fetch as _pg_fetch

        rows = await _pg_fetch(
            "SELECT section_path FROM pipeline_rag_document_embedding "
            "WHERE section_path ILIKE $1 LIMIT 1",
            f"{key}%",
        )
        if rows and rows[0].get("section_path"):
            resolved = key
    except Exception as e:  # noqa: BLE001 — fail-open，绝不因过滤失败阻断检索
        logger.warning("metadata_prefilter resolve failed", hint=key, error=str(e)[:120])
        return None

    _cache[key] = (now + _cache_ttl(ttl_seconds), resolved)
    return resolved


async def resolve_first_section_prefix(hints: list[str]) -> str | None:
    """按顺序返回第一个在语料中验证存在的章节提示；全部未命中返回 None。"""
    for hint in hints:
        resolved = await resolve_section_prefix(hint)
        if resolved:
            return resolved
    return None
