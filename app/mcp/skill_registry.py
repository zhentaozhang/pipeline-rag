"""
Skill 注册/发现中心

职责：
1. 扫描 app/mcp/skills/ 自动发现 BaseSkill 子类
2. 提供 get_tools() / get_system_prompts() / resolve() 供 Agent 使用
3. 与 app/safety/tool_registry.py 的安全管控联动
"""

import importlib
import inspect
import pkgutil
import threading
from collections.abc import Callable

import structlog

from app.mcp.skill_base import BaseSkill, SkillTool
from app.safety.enums import ToolRisk
from app.safety.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)


class SkillRegistry:
    _skills: dict[str, BaseSkill] = {}
    _tool_map: dict[str, SkillTool] = {}
    _discovered: bool = False
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def discover(cls) -> list[BaseSkill]:
        if cls._discovered:
            return list(cls._skills.values())

        with cls._lock:
            if cls._discovered:
                return list(cls._skills.values())

            from app.mcp import skills as skills_pkg

            found: list[BaseSkill] = []
            for _importer, modname, ispkg in pkgutil.iter_modules(skills_pkg.__path__):
                if ispkg:
                    continue
                try:
                    module = importlib.import_module(f"app.mcp.skills.{modname}")
                except Exception:
                    logger.warning("skill_module_load_failed", module=modname, exc_info=True)
                    continue
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BaseSkill)
                        and obj is not BaseSkill
                        and not getattr(obj, "_registered", False)
                    ):
                        skill = obj()
                        cls._register_skill(skill)
                        found.append(skill)
                        obj._registered = True

            cls._discovered = True
            if found:
                logger.info(
                    "skills_discovered",
                    count=len(found),
                    names=[s.name for s in found],
                )
            return found

    @classmethod
    def _register_skill(cls, skill: BaseSkill) -> None:
        if not skill.name:
            raise ValueError(f"Skill must have a name: {type(skill).__name__}")

        cls._skills[skill.name] = skill
        tool_names: list[str] = []
        for tool in skill.get_tools():
            if tool.name in cls._tool_map:
                logger.warning(
                    "duplicate_tool_name",
                    tool_name=tool.name,
                    new_skill=skill.name,
                )
            cls._tool_map[tool.name] = tool
            tool_names.append(tool.name)
            ToolRegistry.register(
                tool.name, getattr(skill, "risk", ToolRisk.MEDIUM), tool.description
            )

        logger.info("skill_registered", name=skill.name, tools=tool_names)

    @classmethod
    def register(cls, skill: BaseSkill) -> None:
        cls._register_skill(skill)

    @classmethod
    def get_tools(cls) -> list[Callable]:
        return [t.fn for t in cls._tool_map.values()]

    @classmethod
    def get_system_prompts(cls) -> str:
        parts = []
        for skill in cls._skills.values():
            if skill.system_prompt_fragment:
                parts.append(skill.system_prompt_fragment.strip())
        return "\n".join(parts)

    @classmethod
    def resolve(cls, tool_name: str) -> SkillTool | None:
        return cls._tool_map.get(tool_name)

    @classmethod
    def list_tools(cls) -> dict[str, str]:
        return {name: tool.description for name, tool in cls._tool_map.items()}

    @classmethod
    def reset(cls) -> None:
        for obj_cls in set(type(s) for s in cls._skills.values()):
            if hasattr(obj_cls, "_registered"):
                del obj_cls._registered
        cls._skills.clear()
        cls._tool_map.clear()
        cls._discovered = False
