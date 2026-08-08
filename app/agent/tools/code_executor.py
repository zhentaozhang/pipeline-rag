"""
Python 代码执行工具（沙箱）

在受限环境中执行 Python 代码，用于数据分析、计算、格式转换。
"""

from __future__ import annotations

import asyncio
import io
import os
import signal
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])

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
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
            return f"受限属性访问被禁止: {node.attr}"

    return None


# 对象逃逸属性链：访问这些 dunder 属性可绕过白名单拿到内部对象（Popen 等）
_FORBIDDEN_ATTRS = frozenset(
    {
        "__class__",
        "__bases__",
        "__base__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__closure__",
        "__code__",
        "__builtins__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__dict__",
        "__module__",
        "__qualname__",
    }
)


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
    代码在沙箱子进程中运行，不支持 import、文件操作、网络请求。

    Args:
        code: 要执行的 Python 代码
        timeout: 执行超时秒数，默认 10 秒

    Returns:
        代码执行的标准输出和错误信息
    """
    if not code or not code.strip():
        return "代码内容不能为空。"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _RUNNER_CODE,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_PROJECT_ROOT,
        start_new_session=os.name == "posix",
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(code.encode("utf-8")),
            timeout=timeout,
        )
    except TimeoutError:
        _kill_process_group(proc)
        await proc.wait()
        return f"代码执行超时（{timeout}秒），请简化计算或分段执行。"
    except Exception:
        _kill_process_group(proc)
        await proc.wait()
        logger.exception("code_executor failed", code_len=len(code), timeout=timeout)
        return "代码执行失败，请重试或简化代码。"

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    if stderr_text:
        if stdout_text:
            return f"执行结果:\n{stdout_text}\n错误:\n{stderr_text}"
        return f"错误:\n{stderr_text}"
    if stdout_text:
        return stdout_text
    return "代码执行成功，无输出。"


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """杀掉子进程及其整个进程组（POSIX）。"""
    if proc.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


_RUNNER_CODE = (
    "import sys\n"
    "from app.agent.tools.code_executor import _execute_sync\n"
    "sys.stdout.write(_execute_sync(sys.stdin.read()))\n"
)
