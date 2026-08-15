"""
WebResearch Skill — 联网搜索

包装现有 tavily_search 工具，提供联网搜索最新信息和网页来源的能力。
"""

from app.agent.graph import tavily_search as _tavily_tool
from app.mcp.skill_base import BaseSkill, SkillTool
from app.safety.enums import ToolRisk


class WebResearchSkill(BaseSkill):
    name = "web_research"
    description = "联网搜索最新信息、新闻和网页来源"
    risk = ToolRisk.MEDIUM
    system_prompt_fragment = (
        "- tavily_search: 当你需要查询外部最新信息、新闻、实时数据时使用。"
        "调用时必须传 JSON 参数，且至少包含非空 query；"
        "可选 topic 和 maxResults，其中 topic 仅允许 general、news、finance。"
    )

    def get_tools(self) -> list[SkillTool]:
        return [
            SkillTool(
                name="tavily_search",
                fn=_tavily_tool.func,
                description="联网搜索最新信息、事实资料和网页来源。"
                "调用时必须传 JSON 参数，且至少包含非空 query；"
                "可选 topic 和 maxResults，其中 topic 仅允许 general、news、finance。",
            )
        ]
