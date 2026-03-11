"""执行器模式标签 — 供 parallel_executor 和 aggregator_executor 共享"""

from app.common.enums import ExecutionMode

MODE_LABELS: dict[ExecutionMode, str] = {
    ExecutionMode.RETRIEVAL: "文档检索",
    ExecutionMode.REACT_AGENT: "联网搜索",
    ExecutionMode.RAG_CHAT: "内部知识库",
    ExecutionMode.GRAPH_ONLY: "文档图谱",
    ExecutionMode.GRAPH_THEN_EVIDENCE: "图谱+证据",
    ExecutionMode.CLARIFICATION: "追问",
    ExecutionMode.OPEN_CHAT: "开放对话",
    ExecutionMode.AGENT: "智能助手",
}


def mode_label(mode: ExecutionMode) -> str:
    return MODE_LABELS.get(mode, mode.value)
