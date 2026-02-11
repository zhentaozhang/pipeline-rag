import json

import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk
from app.document.chunker.utils import count_tokens
from app.infra.id_generator import next_id_str

logger = structlog.get_logger(__name__)


class LLMChunker:
    async def chunk(self, text: str, doc_id: str, config: ChunkConfig) -> list[Chunk]:
        logger.debug("llm chunker started", doc_id=doc_id)

        from app.common.jinja import jinja_env
        from app.common.llm_client import get_chat_client, llm_breaker
        from app.config import get_settings as _get_settings

        settings = _get_settings()

        client = get_chat_client()
        template = jinja_env.get_template("document_llm_split.j2")
        prompt = template.render(source_text=text)
        try:
            async with llm_breaker():
                resp = await client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content.rsplit("\n", 1)[0]

            parsed = json.loads(content)
            if isinstance(parsed, dict):
                chunks_val = parsed.get("chunks")
                if isinstance(chunks_val, list):
                    items = chunks_val
                else:
                    items = (
                        parsed.get("content", []) if isinstance(parsed.get("content"), list) else []
                    )
            elif isinstance(parsed, list):
                items = parsed
            else:
                items = []
            results = []
            for i, item in enumerate(items):
                if isinstance(item, str):
                    txt = item.strip()
                elif isinstance(item, dict):
                    txt = item.get("content", "").strip()
                else:
                    continue
                if not txt or len(txt) < config.min_chunk_size:
                    continue
                results.append(
                    Chunk(
                        chunk_id=next_id_str(),
                        doc_id=doc_id,
                        content=txt,
                        chunk_index=i,
                        chunk_type="child",
                        token_count=count_tokens(txt),
                    )
                )
            logger.debug("llm chunker done", count=len(results))
            return results
        except Exception as e:
            logger.error("llm chunker failed", doc_id=doc_id, error=str(e), exc_info=True)
            return []
