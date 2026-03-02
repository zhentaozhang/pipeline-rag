"""事后诸葛亮推荐追问机制 — 利用 LLM 推测用户可能的下一步追问。"""

import asyncio
import json

import structlog

from app.chat.memory import MemoryContext
from app.common.llm_client import get_chat_client, llm_breaker
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class RecommendationService:
    """在对话流结束后，利用 LLM 推测用户可能的下一步追问"""

    SYSTEM_PROMPT = """你是一个有洞察力的 AI 助手。
现在你刚回答完用户的问题。请根据【历史上下文】、【用户问题】和【你的回答】，推测用户接下来最有可能问的 3 个问题。
要求：
1. 追问必须与当前的上下文紧密相关，且自然。
2. 尽量简短精炼。
3. 请严格按照以下 JSON 格式返回，只返回 JSON，不要返回其他任何内容：
{
  "recommendations": ["追问1", "追问2", "追问3"]
}
"""

    def __init__(self) -> None:
        self._client = get_chat_client()

    async def generate_recommendations(
        self, question: str, answer: str, memory_ctx: MemoryContext
    ) -> list[str]:
        """
        生成推荐追问。
        """
        if not settings.recommendation.enabled:
            return []

        prompt = f"【历史上下文】\n{memory_ctx.to_prompt_text()}\n\n【用户问题】\n{question}\n\n【你的回答】\n{answer[:1000]}..."
        timeout = settings.recommendation.timeout_ms / 1000.0

        try:
            async with llm_breaker():
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=settings.llm.model,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.5,
                        max_tokens=200,
                        response_format={"type": "json_object"},
                    ),
                    timeout=timeout,
                )
            content = response.choices[0].message.content
            if not content:
                return []

            data = json.loads(content)
            return data.get("recommendations", [])[:3]
        except Exception as e:
            logger.warning("failed to generate recommendations", error=str(e))
            return []
