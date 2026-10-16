"""
子执行计划（SubPlan）模型辅助与校验工具函数。

从 Supervisor 模块中抽取，作为单向被依赖的领域下沉工具，
消除 supervisor 与 supervisor_graph 之间的双向循环依赖。
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import structlog

from app.chat.schema import SubPlan
from app.common.enums import ExecutionMode

if TYPE_CHECKING:
    from app.chat.schema import ExecutionPlan

logger = structlog.get_logger(__name__)


def inherit_plan_scope(plan: ExecutionPlan) -> None:
    """把父计划的路由与导航范围下传到子计划。

    仅在子计划真正会被执行时生效（``supervisor_mode`` + ``MULTI_AGENT``），
    评审耗尽后残留的 rejected 子计划不在此列。
    """
    if not plan.supervisor_mode or not plan.sub_plans:
        return
    for sp in plan.sub_plans:
        if not sp.doc_ids:
            sp.doc_ids = list(plan.retrieval_document_ids or [])
        if sp.navigation_decision is None:
            sp.navigation_decision = plan.navigation_decision


def build_sub_plans(raw_plans: list[dict]) -> list[SubPlan]:
    """从原始字典列表构建 SubPlan 对象列表。"""
    sub_plans: list[SubPlan] = []
    for raw in raw_plans:
        mode_str = raw.get("mode", "RETRIEVAL").upper()
        try:
            mode = ExecutionMode(mode_str)
        except ValueError:
            logger.warning("unknown mode in sub_plan", mode=mode_str)
            continue
        sub_plans.append(
            SubPlan(
                id=raw.get("id", str(len(sub_plans) + 1)),
                mode=mode,
                question=raw.get("question", ""),
                depends_on=raw.get("depends_on", []),
            )
        )
    return sub_plans


def validate_sub_plans(sub_plans: list[SubPlan]) -> tuple[bool, list[str]]:
    """结构验证：检查依赖引用有效、无重复 ID、问题非空、无循环依赖。"""
    errors: list[str] = []
    ids = {sp.id for sp in sub_plans}

    if len(ids) != len(sub_plans):
        errors.append("子计划 ID 存在重复")
        return False, errors

    has_invalid_dep = False
    for sp in sub_plans:
        if not sp.question or not sp.question.strip():
            errors.append(f"子计划 {sp.id} 问题为空")
        for dep_id in sp.depends_on:
            if dep_id not in ids:
                errors.append(f"子计划 {sp.id} 依赖 {dep_id} 不存在")
                has_invalid_dep = True

    # 仅在所有依赖 ID 合法时进行环检测
    if not has_invalid_dep and sub_plans:
        in_degree = {sp.id: len(sp.depends_on) for sp in sub_plans}
        dependents: dict[str, list[str]] = defaultdict(list)
        for sp in sub_plans:
            for dep_id in sp.depends_on:
                dependents[dep_id].append(sp.id)

        queue = [sp.id for sp in sub_plans if in_degree[sp.id] == 0]
        visited = 0
        while queue:
            pid = queue.pop(0)
            visited += 1
            for did in dependents.get(pid, []):
                in_degree[did] -= 1
                if in_degree[did] == 0:
                    queue.append(did)

        if visited != len(sub_plans):
            errors.append("子计划依赖存在循环依赖")

    return len(errors) == 0, errors
