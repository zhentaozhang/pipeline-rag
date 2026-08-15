"""
意图分类器

分类结果：
- "knowledge"  — 可以在知识库找到答案
- "open"       — 需要联网搜索或多步推理
- "ambiguous"  — 信息不足，需要歧义追问（初步判断，细化由 QueryRewriter 完成）
"""

import structlog

from app.chat.memory import MemoryContext
from app.common.llm_client import get_chat_client, llm_breaker
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class IntentClassifier:
    """
    基于 LLM 的意图分类。
    使用结构化输出（JSON mode）保证稳定性。
    """

    SYSTEM_PROMPT = """你是一个意图分类助手。根据用户问题，判断其意图类型：
- knowledge: 问题可以从企业知识库文档中找到答案
- open: 问题需要联网搜索实时信息（如天气、新闻）或需要多步推理
- ambiguous: 问题信息量不足，无法确定意图（如"查一下那个"）

只返回 JSON，格式：{"intent": "knowledge|open|ambiguous", "reason": "简短说明"}"""

    def __init__(self) -> None:
        self._client = get_chat_client()

    async def classify(self, question: str, memory_ctx: MemoryContext) -> str:
        logger.debug("intent classify", question=question[:50])
        prompt = f"【最近对话】\n{memory_ctx.to_prompt_text()}\n\n【用户问题】\n{question}"

        try:
            async with llm_breaker():
                response = await self._client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")
            import json

            data = json.loads(content)
            intent: str = data.get("intent", "knowledge")
            if intent not in ["knowledge", "open", "ambiguous"]:
                intent = "knowledge"
            return intent
        except Exception as e:
            logger.error(
                "intent classify failed, fallback to knowledge", error=str(e), exc_info=True
            )
            return "knowledge"
