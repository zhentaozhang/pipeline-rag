"""
ReAct Agent 执行器（LangGraph）
使用 LangGraph StateGraph 构建 ReAct 循环，支持 Tavily 联网搜索等工具调用。
"""

from collections.abc import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.jinja import jinja_env
from app.common.sse import SSEEventType, sse_event
from app.config import get_settings
from app.executors.base import ConversationExecutor
from app.safety.output import OutputFilter, SafetyResponse

logger = structlog.get_logger(__name__)
settings = get_settings()


class ReactAgentExecutor(ConversationExecutor):
    """
    核心执行器：驱动对话智能体。
    基于 ReAct 模式（Reasoning + Acting），具备多步推理和工具调用能力。
    """

    mode = ExecutionMode.REACT_AGENT

    def __init__(self, db: AsyncSession, task: ChatTaskInfo) -> None:
        self.db = db
        self.task = task

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent.graph import build_react_graph
        from app.observability import SpanKind

        tracer = self.task.tracer

        logger.debug("react agent executor", conversation_id=self.task.conversation_id)

        yield sse_event(SSEEventType.THINKING, "当前问题进入开放式 Agent 自主执行阶段。")
        self.task.thinking_steps.append("当前问题进入开放式 Agent 自主执行阶段。")

        if self.task.debug_trace is not None:
            self.task.debug_trace.retrieval_notes.append(
                "当前问题走 ReactAgent 执行路径，由 Agent 自主决定是否调用联网搜索或其他工具。"
            )
        from app.mcp.skill_registry import SkillRegistry

        SkillRegistry.discover()
        skill_prompts = SkillRegistry.get_system_prompts()
        template = jinja_env.get_template("agent_system.j2")
        system_prompt = template.render(
            context_summary=getattr(plan, "context_summary", "") or "",
            current_date_text=getattr(plan, "current_date_text", "") or "",
            requires_current_date_anchoring=bool(
                getattr(plan, "requires_current_date_anchoring", False)
            ),
            requires_fresh_search=bool(getattr(plan, "requires_fresh_search", False)),
            skill_prompts=skill_prompts,
        )

        workflow = build_react_graph()

        import sys as _sys

        span_active = False
        if tracer is not None:
            span_mgr = tracer.span("react_agent", kind=SpanKind.AGENT)
            await span_mgr.__aenter__()
            span_active = True
        try:
            agent_question = plan.agent_question
            if not agent_question:
                agent_question = plan.rewritten_question
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=agent_question)]

            # P2-1：彻底移除 LangGraph checkpoint 持久化（AIOMySQLSaver）——
            # 每次请求都是单轮一次性执行，从不跨请求恢复，checkpoint 写后即弃；
            # 改用无 checkpointer 编译，终态从最后一次节点更新累积。
            graph = workflow.compile()

            async for event in graph.astream({"messages": messages}, stream_mode="updates"):
                for node_name, state_update in event.items():
                    if node_name == "agent":
                        msgs = state_update.get("messages", [])
                        if msgs:
                            last_msg = msgs[-1]
                            has_content = bool(last_msg.content)
                            has_tool_calls = bool(getattr(last_msg, "tool_calls", None))
                            if not has_content and not has_tool_calls:
                                continue
                            if has_content and not has_tool_calls:
                                output_filter = OutputFilter()
                                output_result = await output_filter.filter(last_msg.content)
                                if not output_result.safe:
                                    logger.warning(
                                        "output_filter_blocked_agent", reason=output_result.reason
                                    )
                                    yield self._emit(
                                        SSEEventType.TEXT,
                                        SafetyResponse.get_block_message(output_result.reason),
                                    )
                                else:
                                    yield self._emit(SSEEventType.TEXT, last_msg.content)

                            if has_tool_calls:
                                for tc in last_msg.tool_calls:
                                    tool_think = f"正在调用工具 {tc['name']}..."
                                    self.task.thinking_steps.append(tool_think)
                                    yield self._emit(SSEEventType.THINKING, tool_think)

                        model_count = state_update.get("model_call_count")
                        if model_count:
                            self.task.model_call_count = model_count

                    elif node_name == "tools":
                        tool_count = state_update.get("tool_call_count")
                        if tool_count:
                            self.task.tool_call_count = tool_count
                            tool_result_think = "获取信息完成，正在分析结果..."
                            self.task.thinking_steps.append(tool_result_think)
                            yield self._emit(SSEEventType.THINKING, tool_result_think)
                        session_tool_count = state_update.get("session_tool_call_count")
                        if session_tool_count:
                            self.task.tool_call_count = session_tool_count
        except Exception as e:
            logger.error("agent execution failed", error=str(e), exc_info=True)
            raise
        finally:
            if span_active:
                await span_mgr.__aexit__(*_sys.exc_info())
