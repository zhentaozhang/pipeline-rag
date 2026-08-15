"""
MCP Skill 抽象基类

每个 Skill 是一个自治模块，提供：
- tools: 可被 Agent 调用的工具函数
- system_prompt_fragment: 注入 Agent system prompt 的说明文本
- risk: 安全风险等级（与 app/safety/tool_registry.py 联动）
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from app.safety.enums import ToolRisk


@dataclass
class SkillTool:
    """Skill 内部的工具描述"""

    name: str
    fn: Callable
    description: str = ""
    parameters: dict | None = field(default=None)


class BaseSkill(ABC):
    """
    Skill 抽象基类。

    子类必须定义类属性：
      name, description, risk, system_prompt_fragment

    子类必须实现：
      get_tools() → list[SkillTool]

    可选钩子：
      on_register() — 注册到 ToolRegistry 等
      on_unregister() — 清理
    """

    name: str = ""
    description: str = ""
    risk: ToolRisk = ToolRisk.MEDIUM
    system_prompt_fragment: str = ""
    # 运行时标记：是否已注册到 SkillRegistry（由 skill_registry 维护）
    _registered: ClassVar[bool] = False

    @abstractmethod
    def get_tools(self) -> list[SkillTool]:
        """返回本 Skill 提供的所有工具（Callable 须可被 langchain bind_tools 识别）"""

    async def on_register(self) -> None:  # noqa: B027
        """注册到 ToolRegistry 时的钩子"""
        pass

    async def on_unregister(self) -> None:  # noqa: B027
        """注销时的清理钩子"""
        pass
