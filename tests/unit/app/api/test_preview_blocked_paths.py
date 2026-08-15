"""
Preview 只读模式拦截清单的防回归测试。

PREVIEW_BLOCKED_PATHS 必须覆盖所有 /manage/** 写操作路由，
否则线上只读演示模式存在绕过路径。只读查询接口（query/list/overview 等）
允许放行，但需在 READONLY_MANAGE_PATHS 中显式声明。
"""

import glob
import re

from app.api.admin_auth import PREVIEW_BLOCKED_PATHS

# POST 动词但为只读语义的接口：preview 模式允许放行（浏览/检索能力）
READONLY_MANAGE_PATHS = frozenset(
    {
        "/manage/document/page/query",
        "/manage/document/detail/query",
        "/manage/document/chunk/query",
        "/manage/document/chunk/detail/query",
        "/manage/document/strategy/plan/query",
        "/manage/document/strategy/recommend",
        "/manage/document/task/log/query",
        "/manage/evaluation/dataset/page/query",
        "/manage/knowledge/document/profile/detail",
        "/manage/knowledge/route/trace/page/query",
        "/manage/knowledge/scope/list",
        "/manage/knowledge/topic/document/list",
        "/manage/knowledge/topic/list",
        "/manage/metrics/overview",
        "/manage/metrics/usage-trend",
    }
)


def _collect_manage_write_paths() -> set[str]:
    """扫描 app/api/manage_*.py 中所有写路由（post/put/delete/patch）的完整路径"""
    paths: set[str] = set()
    for f in glob.glob("app/api/manage_*.py"):
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        for m in re.finditer(r'@router\.(post|put|delete|patch)\([^)]*?"(/[^"]+)"', src, re.S):
            paths.add("/manage" + m.group(2))
    return paths


def test_preview_blocks_all_manage_write_endpoints():
    all_routes = _collect_manage_write_paths()
    write_routes = all_routes - READONLY_MANAGE_PATHS
    missing = write_routes - PREVIEW_BLOCKED_PATHS
    assert not missing, f"preview 只读模式未拦截以下写接口: {sorted(missing)}"


def test_preview_blocked_paths_all_under_manage():
    """拦截清单中的 /manage/** 路径必须是真实存在的路由（防止死条目）"""
    real = _collect_manage_write_paths()
    stale = {p for p in PREVIEW_BLOCKED_PATHS if p.startswith("/manage/")} - real
    assert not stale, f"preview 拦截清单包含不存在的路由: {sorted(stale)}"


def test_readonly_paths_are_real_routes():
    """READONLY_MANAGE_PATHS 中的路径必须真实存在（防止幽灵条目）"""
    real = _collect_manage_write_paths()
    ghost = READONLY_MANAGE_PATHS - real
    assert not ghost, f"READONLY_MANAGE_PATHS 包含不存在的路由: {sorted(ghost)}"
