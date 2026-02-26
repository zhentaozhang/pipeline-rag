"""
会话记忆策略

三种策略：
1. NoMemory          — 无记忆，每轮独立
2. SlidingWindow     — 保留最近 N 轮完整对话
3. SummaryCompression — 长期摘要 + 最近原文窗口（生产推荐方案）
"""

import re
from abc import ABC, abstractmethod
from collections import OrderedDict

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.transcript_renderer import HistoryTurn, TranscriptRenderer, clip_text
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Turn status constants ──────────────────────────────────────────────────────
TURN_RUNNING = 1
TURN_COMPLETED = 2
TURN_FAILED = 3
TURN_STOPPED = 4

# ── Token budget / clipping constants ──────────────────────────────────────────
MAX_SECTION_ITEMS = settings.memory.max_section_items
MAX_ITEM_LENGTH = settings.memory.max_item_length
MAX_GOAL_LENGTH = 120
MAX_ANSWER_CONTEXT_ANSWER_LENGTH = 220

RETRIEVAL_HINT_PATTERN = re.compile(r"[a-zA-Z0-9._-]{2,}|[\u4e00-\u9fff]{2,12}")
NOISE_HINT_WORDS = {
    "请问",
    "帮我",
    "一下",
    "如何",
    "怎么",
    "什么",
    "哪个",
    "这个",
    "那个",
    "可以",
    "需要",
}


# ── 数据结构 ──────────────────────────────────────────────────────────────────


class ConversationSummaryPayload(BaseModel):
    """长期会话摘要的结构化载体"""

    summary: str = ""
    conversation_goal: str = Field(default="", alias="conversationGoal")
    stable_facts: list[str] = Field(default_factory=list, alias="stableFacts")
    user_preferences: list[str] = Field(default_factory=list, alias="userPreferences")
    resolved_points: list[str] = Field(default_factory=list, alias="resolvedPoints")
    pending_questions: list[str] = Field(default_factory=list, alias="pendingQuestions")
    retrieval_hints: list[str] = Field(default_factory=list, alias="retrievalHints")

    model_config = {"populate_by_name": True}





def deduplicate_and_limit(values: list[str]) -> list[str]:
    """有序去重 + 截断 + 数量限制"""
    seen: OrderedDict[str, None] = OrderedDict()
    for value in values:
        text = clip_text(value or "", MAX_ITEM_LENGTH)
        if text and text not in seen:
            seen[text] = None
        if len(seen) >= MAX_SECTION_ITEMS:
            break
    return list(seen.keys())


def extract_retrieval_hints(question: str) -> list[str]:
    """从提问中提取检索提示词"""
    if not question or not question.strip():
        return []
    hints: OrderedDict[str, None] = OrderedDict()
    for m in RETRIEVAL_HINT_PATTERN.finditer(question):
        hint = m.group().strip()
        if len(hint) >= 2 and hint not in NOISE_HINT_WORDS:
            hints[clip_text(hint, MAX_ITEM_LENGTH)] = None
        if len(hints) >= MAX_SECTION_ITEMS:
            break
    return list(hints.keys())


class MemoryContext:
    """记忆上下文，传递给 Orchestrator 和 Executor 使用"""

    def __init__(
        self,
        summary_payload: ConversationSummaryPayload | None = None,
        recent_turns: list[HistoryTurn] | None = None,
        long_term_summary: str = "",
        recent_transcript: str = "",
        answer_recent_transcript: str = "",
        assembled_history: str = "",
        covered_exchange_id: int = 0,
        covered_exchange_count: int = 0,
        compression_count: int = 0,
        compression_applied: bool = False,
    ) -> None:
        self.summary_payload = summary_payload or ConversationSummaryPayload()
        self.recent_turns = recent_turns or []  # 最近原文窗口
        self.long_term_summary = long_term_summary
        self.recent_transcript = recent_transcript
        self.answer_recent_transcript = answer_recent_transcript
        self.assembled_history = assembled_history
        self.covered_exchange_id = covered_exchange_id
        self.covered_exchange_count = covered_exchange_count
        self.compression_count = compression_count
        self.compression_applied = compression_applied

    def to_prompt_text(self) -> str:
        """拼接为 Prompt 可用的结构化上下文文本"""
        parts: list[str] = []
        payload = self.summary_payload

        # 1. 长期会话摘要
        if payload.summary:
            parts.append(f"【长期会话摘要】\n{payload.summary}")

        # 2. 会话目标
        if payload.conversation_goal:
            parts.append(f"【会话目标】\n{payload.conversation_goal}")

        # 3. 已确认事实
        if payload.stable_facts:
            facts = "\n".join(f"- {f}" for f in payload.stable_facts)
            parts.append(f"【已确认事实】\n{facts}")

        # 4. 用户偏好与约束
        if payload.user_preferences:
            prefs = "\n".join(f"- {p}" for p in payload.user_preferences)
            parts.append(f"【用户偏好与约束】\n{prefs}")

        # 5. 已解决问题
        if payload.resolved_points:
            resolved = "\n".join(f"- {r}" for r in payload.resolved_points)
            parts.append(f"【已解决问题】\n{resolved}")

        # 6. 待跟进问题
        if payload.pending_questions:
            qs = "\n".join(f"- {q}" for q in payload.pending_questions)
            parts.append(f"【待跟进问题】\n{qs}")

        # 7. 检索提示
        if payload.retrieval_hints:
            hints = "\n".join(f"- {h}" for h in payload.retrieval_hints)
            parts.append(f"【检索提示】\n{hints}")

        return "\n".join(parts)


# ── 策略接口 ──────────────────────────────────────────────────────────────────


class MemoryStrategy(ABC):
    """记忆策略基类"""

    @abstractmethod
    async def load(self, conversation_id: str, db: AsyncSession) -> MemoryContext:
        """加载当前会话的记忆上下文"""

    @abstractmethod
    async def save(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        db: AsyncSession,
        exchange_id: int | None = None,
    ) -> None:
        """保存本轮对话到记忆"""


# ── 无记忆 ────────────────────────────────────────────────────────────────────


class NoMemoryStrategy(MemoryStrategy):
    """无记忆 — 每轮独立，适合一次性查询"""

    async def load(self, conversation_id: str, db: AsyncSession) -> MemoryContext:
        return MemoryContext()

    async def save(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        db: AsyncSession,
        exchange_id: int | None = None,
    ) -> None:
        pass  # 不保存任何历史


# ── 滑动窗口 ──────────────────────────────────────────────────────────────────


class SlidingWindowStrategy(MemoryStrategy):
    """
    滑动窗口 — 保留最近 N 轮完整对话。
    适合短期连续追问，Token 成本可控。
    """

    def __init__(self, window_size: int | None = None) -> None:
        self.window_size = window_size or settings.memory.window_size

    async def load(self, conversation_id: str, db: AsyncSession) -> MemoryContext:
        from sqlalchemy import desc, select

        from app.db.models.conversation import ConversationExchange

        result = await db.execute(
            select(ConversationExchange)
            .where(ConversationExchange.conversation_id == conversation_id)
            .order_by(desc(ConversationExchange.id))
            .limit(self.window_size)
        )
        exchanges = list(reversed(result.scalars().all()))
        turns = [HistoryTurn(e.question, e.answer or "") for e in exchanges]
        return MemoryContext(recent_turns=turns)

    async def save(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        db: AsyncSession,
        exchange_id: int | None = None,
    ) -> None:
        pass  # Exchange 由 BusinessChatService 统一保存


# ── 摘要压缩 ──────────────────────────────────────────────────────────────────


class SummaryCompressionStrategy(MemoryStrategy):
    """
     摘要压缩（生产推荐方案）。

     设计：
     - 最近 window_size 轮原文始终保留
     - 更早的历史增量摘要（每次最多推进 batch_size 轮）
     - 长期摘要最大 max_summary_chars 字符
     - 最近原文最大 max_window_chars 字符
     """

    async def load(self, conversation_id: str, db: AsyncSession) -> MemoryContext:
        from sqlalchemy import desc, select

        from app.db.models.conversation import ConversationExchange, ConversationMemory

        # When summary is disabled, just render recent transcript
        if not settings.memory.enabled:
            fetch_limit = max(settings.memory.window_size * 3, settings.memory.window_size + 4)
            result = await db.execute(
                select(ConversationExchange)
                .where(ConversationExchange.conversation_id == conversation_id)
                .order_by(desc(ConversationExchange.id))
                .limit(fetch_limit)
            )
            all_exchanges = list(reversed(result.scalars().all()))
            renderable = [
                e
                for e in all_exchanges
                if e
                and e.turn_status is not None
                and e.turn_status != TURN_RUNNING
                and (e.question or e.answer)
            ]
            recent_turns = [
                HistoryTurn(e.question, e.answer or "")
                for e in renderable[-settings.memory.window_size :]
            ]
            recent_transcript = TranscriptRenderer.render_recent_transcript(recent_turns)
            answer_recent_transcript = TranscriptRenderer.render_answer_recent_transcript(recent_turns)
            return MemoryContext(
                long_term_summary="",
                recent_transcript=recent_transcript,
                answer_recent_transcript=answer_recent_transcript,
                assembled_history=recent_transcript,
                recent_turns=recent_turns,
                compression_applied=False,
            )

        # 加载摘要记录
        mem_result = await db.execute(
            select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        )
        mem = mem_result.scalar_one_or_none()
        summary_payload = ConversationSummaryPayload()
        covered_exchange_id = 0
        covered_exchange_count = 0
        compression_count = 0
        long_term_summary = ""
        compression_applied = False

        if mem:
            covered_exchange_id = mem.covered_exchange_id or 0
            covered_exchange_count = mem.covered_exchange_count or 0
            compression_count = mem.compression_count or 0
            if mem.summary_json:
                try:
                    summary_payload = ConversationSummaryPayload.model_validate_json(
                        mem.summary_json
                    )
                except Exception as e:
                    logger.warning(
                        "failed to parse structured summary, fallback to text",
                        error=str(e),
                        exc_info=True,
                    )
                    summary_payload.summary = mem.summary_json
                long_term_summary = mem.summary_text or ""
                compression_applied = bool(long_term_summary and long_term_summary.strip())

        # 加载最近原文窗口
        fetch_limit = max(settings.memory.window_size * 3, settings.memory.window_size + 4)
        result = await db.execute(
            select(ConversationExchange)
            .where(ConversationExchange.conversation_id == conversation_id)
            .order_by(desc(ConversationExchange.id))
            .limit(fetch_limit)
        )
        all_exchanges = list(reversed(result.scalars().all()))

        # Filter to renderable exchanges
        # status != RUNNING && (question not blank || answer not blank)
        renderable = [
            e
            for e in all_exchanges
            if e
            and e.turn_status is not None
            and e.turn_status != TURN_RUNNING
            and (e.question or e.answer)
        ]
        recent_turns = [
            HistoryTurn(e.question, e.answer or "")
            for e in renderable[-settings.memory.window_size :]
        ]

        # Build recent transcript text
        recent_transcript = TranscriptRenderer.render_recent_transcript(recent_turns)
        # Build answer recent transcript
        answer_recent_transcript = TranscriptRenderer.render_answer_recent_transcript(recent_turns)
        # Assemble history
        assembled_history = TranscriptRenderer.assemble_history(long_term_summary, recent_transcript)

        return MemoryContext(
            summary_payload=summary_payload,
            recent_turns=recent_turns,
            long_term_summary=long_term_summary,
            recent_transcript=recent_transcript,
            answer_recent_transcript=answer_recent_transcript,
            assembled_history=assembled_history,
            covered_exchange_id=covered_exchange_id,
            covered_exchange_count=covered_exchange_count,
            compression_count=compression_count,
            compression_applied=compression_applied,
        )

    async def save(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        db: AsyncSession,
        exchange_id: int | None = None,
    ) -> None:
        """
        保存后触发异步增量摘要（若超出 window_size 则对旧轮次做摘要压缩）。
        :param exchange_id: 最新 exchange ID，传递给 Celery 用于避免脏读
        """
        from app.chat.tasks import task_compress_conversation_memory

        task_compress_conversation_memory.delay(conversation_id, exchange_id)
        logger.info("memory compression task dispatched", conversation_id=conversation_id)

    async def compress_history(
        self, conversation_id: str, db: AsyncSession, known_exchange_id: int | None = None
    ) -> None:
        from app.chat.memory_compressor import ConversationMemoryCompressor

        compressor = ConversationMemoryCompressor()
        await compressor.compress_history(
            conversation_id, db, known_exchange_id=known_exchange_id
        )




# ── 工厂函数 ──────────────────────────────────────────────────────────────────


def create_memory_strategy(strategy: str | None = None) -> MemoryStrategy:
    """
    根据配置或参数创建对应的记忆策略实例。
    策略工厂模式：根据配置名选择对应的记忆策略实现。
    """
    s = strategy or settings.memory.strategy
    if s == "none":
        return NoMemoryStrategy()
    elif s == "sliding_window":
        return SlidingWindowStrategy()
    elif s == "summary_compression":
        return SummaryCompressionStrategy()
    else:
        logger.warning("unknown memory strategy, fallback to sliding_window", strategy=s)
        return SlidingWindowStrategy()
