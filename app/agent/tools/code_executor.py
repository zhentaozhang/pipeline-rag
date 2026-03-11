"""
Python 代码执行工具（沙箱）

在受限环境中执行 Python 代码，用于数据分析、计算、格式转换。
"""

from __future__ import annotations

import asyncio
import io
import sys
import traceback
from contextlib import redirect_stdout

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)

_SAFE_BUILTINS: dict[str, object] = {
    "abs": abs,
    "all": all,
    "any": any,
    "ascii": ascii,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hasattr": hasattr,
    "hash": hash,
    "hex": hex,
    "id": id,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "vars": vars,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


def _check_code_safety(code: str) -> str | None:
    """检查代码安全性，返回错误信息或 None（安全）。"""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"代码语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                return f"import 操作被禁止: {alias.name}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in (
                "exec",
                "eval",
                "compile",
                "__import__",
                "open",
            ):
                return f"危险函数被禁止: {node.func.id}"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in ("open",):
                return "文件操作被禁止: open"

    return None


def _execute_sync(code: str) -> str:
    """同步执行代码，返回输出。"""
    safety_error = _check_code_safety(code)
    if safety_error:
        return safety_error

    restricted_globals: dict[str, object] = {
        "__builtins__": _SAFE_BUILTINS,
    }

    stdout = io.StringIO()
    stderr = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr

    try:
        with redirect_stdout(stdout):
            exec(code, restricted_globals)
    except Exception:
        traceback.print_exc(file=stderr)
    finally:
        sys.stderr = original_stderr

    output = stdout.getvalue()
    error = stderr.getvalue()

    if error:
        if output:
            return f"执行结果:\n{output}\n错误:\n{error}"
        return f"错误:\n{error}"
    if output:
        return output
    return "代码执行成功，无输出。"


@tool
async def code_executor(code: str, timeout: int = 10) -> str:
    """
    执行 Python 代码并返回运行结果。适用于数据分析、数值计算、格式转换等任务。
    代码在沙箱环境中运行，不支持 import、文件操作、网络请求。

    Args:
        code: 要执行的 Python 代码
        timeout: 执行超时秒数，默认 10 秒

    Returns:
        代码执行的标准输出和错误信息
    """
    if not code or not code.strip():
        return "代码内容不能为空。"

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _execute_sync, code),
            timeout=timeout,
        )
        logger.info("code_executor success", code_len=len(code), timeout=timeout)
        return result
    except TimeoutError:
        return f"代码执行超时（{timeout}秒），请简化计算或分段执行。"
    except Exception as e:
        logger.exception("code_executor failed", code_len=len(code))
        return f"代码执行异常: {e}"
