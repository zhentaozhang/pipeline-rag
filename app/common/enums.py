"""
统一全局枚举类
使用 Python 原生 Enum 类型（IntEnum / StrEnum）。
"""

from enum import IntEnum, StrEnum


class DocumentTaskTypeEnum(IntEnum):
    PARSE_ROUTE = 1
    BUILD_INDEX = 2


class DocumentTaskStageEnum(IntEnum):
    FILE_UPLOAD = 1
    CONTENT_PARSE = 2
    STRATEGY_ROUTE = 3
    STRATEGY_CONFIRM = 4
    CHUNK_EXECUTE = 5
    CHUNK_POST_PROCESS = 6
    VECTORIZE = 7
    STORE_COMPLETE = 8


class DocumentStrategyRoleEnum(IntEnum):
    """文档策略角色：主策略/优化策略/兜底策略/增强策略"""

    PRIMARY = 1
    OPTIMIZE = 2
    FALLBACK = 3
    ENHANCE = 4


class DocumentChunkSourceTypeEnum(IntEnum):
    ORIGINAL = 1
    ENRICHED = 2


class DocumentStructureNodeTypeEnum(IntEnum):
    DOCUMENT = 1
    SECTION = 2
    STEP = 3
    LIST_ITEM = 4


class ChatQueryMode(IntEnum):
    """对话查询模式：文档问答 / 开放聊天 / 自动文档路由"""

    DOCUMENT = 1
    OPEN_CHAT = 2
    AUTO_DOCUMENT = 3


_CHAT_MODE_ALIASES: dict[str, ChatQueryMode] = {
    "auto": ChatQueryMode.AUTO_DOCUMENT,
    "auto_document": ChatQueryMode.AUTO_DOCUMENT,
    "open_chat": ChatQueryMode.OPEN_CHAT,
    "openchat": ChatQueryMode.OPEN_CHAT,
    "document": ChatQueryMode.DOCUMENT,
    "doc": ChatQueryMode.DOCUMENT,
}


def normalize_chat_mode(value: str) -> ChatQueryMode:
    key = value.strip().lower()
    if key in _CHAT_MODE_ALIASES:
        return _CHAT_MODE_ALIASES[key]
    mode = ChatQueryMode.__members__.get(key.upper())
    if mode is None:
        raise ValueError(f"Invalid chat mode: {value!r}")
    return mode


class ExecutionMode(StrEnum):
    """执行器模式"""

    RETRIEVAL = "RETRIEVAL"
    REACT_AGENT = "REACT_AGENT"
    CLARIFICATION = "CLARIFICATION"
    GRAPH_ONLY = "GRAPH_ONLY"
    GRAPH_THEN_EVIDENCE = "GRAPH_THEN_EVIDENCE"
    OPEN_CHAT = "OPEN_CHAT"
    AGENT = "AGENT"
    RAG_CHAT = "RAG_CHAT"
    REFUSAL = "REFUSAL"
    MULTI_AGENT = "MULTI_AGENT"


class ChatSessionStatus(IntEnum):
    """会话状态：空闲 / 运行中"""

    IDLE = 1
    RUNNING = 2


class ChatTurnStatus(IntEnum):
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    STOPPED = 4


# ---- Phase 26 Added Enums ----


class DocumentTaskEventTypeEnum(IntEnum):
    """文档任务事件类型：开始/完成/失败/推荐策略/用户调整/用户确认"""

    START = 1
    COMPLETE = 2
    FAILED = 3
    RECOMMEND_STRATEGY = 4
    USER_ADJUST = 5
    USER_CONFIRM = 6


class DocumentStorageTypeEnum(IntEnum):
    MINIO = 1


class DocumentParseStatusEnum(IntEnum):
    WAIT_PARSE = 1
    PARSING = 2
    PARSE_SUCCESS = 3
    PARSE_FAILED = 4


class DocumentLogLevelEnum(IntEnum):
    INFO = 1
    WARN = 2
    ERROR = 3


class DocumentOperatorTypeEnum(IntEnum):
    SYSTEM = 1
    USER = 2
    ADMIN = 3


class DocumentFileTypeEnum(IntEnum):
    PDF = 1
    DOC = 2
    DOCX = 3
    TXT = 4
    MD = 5
    HTML = 6


class DocumentIndexStatusEnum(IntEnum):
    WAIT_BUILD = 1
    BUILDING = 2
    BUILD_SUCCESS = 3
    BUILD_FAILED = 4


class DocumentStrategyStatusEnum(IntEnum):
    WAIT_RECOMMEND = 1
    RECOMMENDED = 2
    CONFIRMED = 3
    EXPIRED = 4


class DocumentTaskStatusEnum(IntEnum):
    NEW = 1
    RUNNING = 2
    SUCCESS = 3
    FAILED = 4
    CANCELED = 5


class DocumentVectorStatusEnum(IntEnum):
    WAIT_VECTOR = 1
    VECTORIZING = 2
    VECTOR_SUCCESS = 3
    VECTOR_FAILED = 4


class BusinessStatus(IntEnum):
    """通用业务二值状态：是/否"""

    NO = 0
    YES = 1


class TraceStageCodeEnum(StrEnum):
    MEMORY = "MEMORY"
    INTENT = "INTENT"
    REWRITE = "REWRITE"
    ROUTE = "ROUTE"
    RAG_RETRIEVE = "RAG_RETRIEVE"
    EVIDENCE_BUDGET = "EVIDENCE_BUDGET"
    GRAPH_QUERY = "GRAPH_QUERY"
    REACT_AGENT = "REACT_AGENT"
    RECOMMENDATION = "RECOMMENDATION"
    ANSWER_GENERATE = "ANSWER_GENERATE"
    FINALIZE = "FINALIZE"


class ConversationTraceStageState(IntEnum):
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    SKIPPED = 4


class NavigationScopeMode(IntEnum):
    """导航作用域模式：无限制/硬性章节/硬性条目/硬性父级+同级"""

    SOFT = 0
    HARD_SECTION = 1
    HARD_ITEM = 2
    HARD_PARENT_WITH_SIBLINGS = 3


class DocumentPipelineStageEnum(IntEnum):
    """文档流水线执行阶段（标识已完成的最近一步）"""

    INIT = 0
    PARSED = 1
    CHUNKED = 2
    VECTORIZED = 3
    INDEXED = 4
    PROFILED = 5
    FAILED = -1


class DocumentNavigationAction(StrEnum):
    """文档导航操作分类：继续话题/切换/刷新/同级切换/深入子级/返回父级/引用条目/未知"""

    TOPIC_CONTINUE = "TOPIC_CONTINUE"
    SWITCH = "SWITCH"
    FRESH = "FRESH"
    SIBLING_SWITCH = "SIBLING_SWITCH"
    CHILD_DESCEND = "CHILD_DESCEND"
    ANCESTOR_RETURN = "ANCESTOR_RETURN"
    ITEM_REFERENCE = "ITEM_REFERENCE"
    UNKNOWN = "UNKNOWN"
