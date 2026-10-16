from __future__ import annotations

from typing import Any, overload


@overload
def safe_int(s: Any, default: int = ...) -> int: ...


@overload
def safe_int(s: Any, default: None = ...) -> int | None: ...


def safe_int(s: Any, default: int | None = 0) -> int | None:
    """宽松整数转换。

    转换失败（ValueError / TypeError）时返回 ``default``。

    返回类型由 ``default`` 决定：不传或传 ``int`` 时静态类型为 ``int``；
    显式传 ``default=None`` 时静态类型为 ``int | None``，便于调用方区分
    "转换失败" 与 "0"。
    """
    try:
        return int(s)
    except (ValueError, TypeError):
        return default
