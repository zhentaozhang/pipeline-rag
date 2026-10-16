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


def stable_id_to_int(val: Any) -> int:
    """将 ID（数字或非数字字符串）稳定映射为 64-bit 整数。

    如果是整数或纯数字字符串，直接转换为 int；
    如果是非数字字符串（如 'parent-0', 'c1'），采用确定性 MD5 摘要映射为 15 位正整数，
    保证跨服务、跨进程、多次调用间映射完全确定且一致。
    """
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if s.isdigit():
        return int(s)
    import hashlib

    digest = hashlib.md5(s.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (10**15)
