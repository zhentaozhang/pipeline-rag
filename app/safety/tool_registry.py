"""
L2 工具准入控制

提供 Agent 工具的注册、风险分级和审批策略。
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from app.infra.metrics import TOOL_APPROVAL_DURATION, TOOL_CALL_TOTAL
from app.safety.enums import ToolRisk

logger = structlog.get_logger(__name__)


@dataclass
class ToolSpec:
    name: str
    risk: ToolRisk
    description: str = ""
    enabled: bool = True


class ToolRegistry:
    """
    Agent 工具注册表。

    管理所有可用工具的元数据、风险等级和启用状态。
    """

    _tools: dict[str, ToolSpec] = {}

    @classmethod
    def register(cls, name: str, risk: ToolRisk, description: str = "") -> ToolSpec:
        spec = ToolSpec(name=name, risk=risk, description=description)
        cls._tools[name] = spec
        logger.debug("tool_registered", name=name, risk=risk.value)
        return spec

    @classmethod
    def get(cls, name: str) -> ToolSpec | None:
        return cls._tools.get(name)

    @classmethod
    def get_risk(cls, name: str) -> ToolRisk:
        spec = cls._tools.get(name)
        return spec.risk if spec else ToolRisk.HIGH

    @classmethod
    def is_enabled(cls, name: str) -> bool:
        spec = cls._tools.get(name)
        return spec.enabled if spec else False

    @classmethod
    def set_enabled(cls, name: str, enabled: bool) -> None:
        spec = cls._tools.get(name)
        if spec:
            spec.enabled = enabled

    @classmethod
    def list_tools(cls) -> dict[str, ToolRisk]:
        return {name: spec.risk for name, spec in cls._tools.items()}

    @classmethod
    def reset(cls) -> None:
        cls._tools.clear()


class ApprovalPolicy:
    """
    工具审批策略。

    根据工具风险等级和具体参数，动态决定是否需要人工审批。

    规则：
    - CRITICAL: 始终需要审批
    - HIGH: 参数包含危险操作（DELETE/DROP/TRUNCATE）时需要审批
    - MEDIUM/LOW: 自动放行
    """

    # 高风险关键词——出现则触发审批
    _HIGH_RISK_KEYWORDS = ["DELETE", "DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE"]

    def __init__(
        self,
        registry: type[ToolRegistry] | None = None,
        custom_policy: Callable[[str, dict], bool] | None = None,
    ) -> None:
        self._registry = registry or ToolRegistry
        self._custom_policy = custom_policy

    async def require_approval(self, tool_name: str, args: dict) -> bool:
        """
        判断工具调用是否需要审批。

        返回 True 表示需要人工确认。
        """
        start = _time.monotonic()
        if self._custom_policy:
            try:
                if await _maybe_awaitable(self._custom_policy, tool_name, args):
                    TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(
                        _time.monotonic() - start
                    )
                    TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="false").inc()
                    return True
            except Exception as e:
                logger.error("custom_policy_failed", error=str(e))
                TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(
                    _time.monotonic() - start
                )
                TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="false").inc()
                return True  # 自定义策略异常时默认审批

        risk = self._registry.get_risk(tool_name)

        elapsed = _time.monotonic() - start

        if risk == ToolRisk.CRITICAL:
            TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(elapsed)
            TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="false").inc()
            logger.warning("approval_required_critical", tool=tool_name)
            return True

        if risk == ToolRisk.HIGH:
            args_str = str(args).upper()
            for kw in self._HIGH_RISK_KEYWORDS:
                if kw in args_str:
                    TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(elapsed)
                    TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="false").inc()
                    logger.warning(
                        "approval_required_high_risk_operation", tool=tool_name, keyword=kw
                    )
                    return True
            # JEV 语义补充：按参数语义识别高风险/破坏性操作（只增不减）
            if await self._semantic_param_risk(tool_name, args):
                TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(
                    _time.monotonic() - start
                )
                TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="false").inc()
                logger.warning("approval_required_semantic_risk", tool=tool_name)
                return True
            TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(elapsed)
            TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="true").inc()
            return False

        TOOL_APPROVAL_DURATION.labels(tool_name=tool_name).observe(elapsed)
        TOOL_CALL_TOTAL.labels(tool_name=tool_name, approved="true").inc()
        return False  # MEDIUM 和 LOW 自动放行

    async def _semantic_param_risk(self, tool_name: str, args: dict) -> bool:
        """JEV Noul 语义补充：参数级高风险判定；关闭/异常时返回 False（不影响规则结论）。"""
        try:
            from app.config import get_settings

            jev_cfg = getattr(get_settings(), "jev", None)
            if not (jev_cfg and getattr(jev_cfg, "tool_risk_semantic_enabled", True)):
                return False

            from app.infra.jev_client import get_jev_client

            answers = await get_jev_client().system_one(
                state=f"工具：{tool_name}\n调用参数：{str(args)[:1500]}",
                questions={
                    "risk": {
                        "type": "noul",
                        "instructions": (
                            "该工具调用参数是否涉及高风险或破坏性操作（删除/覆盖数据、"
                            "执行代码、访问敏感数据、批量修改、外发数据等）？"
                        ),
                    }
                },
            )
            res = answers.get("risk")
            if not isinstance(res, dict) or "noul" not in res:
                return False
            return float(res["noul"]) >= 0.5
        except Exception as e:
            logger.warning("JEV 参数风险判定失败，跳过", error=str(e)[:120])
            return False


async def _maybe_awaitable(func: Callable, *args: Any, **kwargs: Any) -> bool:
    """统一处理 sync/async callable"""
    result = func(*args, **kwargs)
    if hasattr(result, "__await__"):
        return bool(await result)
    return bool(result)
