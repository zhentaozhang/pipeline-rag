from __future__ import annotations


def safe_int(s, default: int | None = 0) -> int | None:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default
