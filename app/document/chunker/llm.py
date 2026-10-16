import json

import structlog

from app.document.chunker.config import ChunkConfig
from app.document.chunker.models import Chunk
from app.document.chunker.utils import count_tokens
from app.infra.id_generator import next_id_str

logger = structlog.get_logger(__name__)


class LLMChunker:
    async def chunk(self, text: str, doc_id: str, config: ChunkConfig) -> list[Chunk]:
        logger.debug("llm chunker started", doc_id=doc_id, length=len(text))
        if not text or not text.strip():
            return []

        # 分段处理：若文本较长（>4000 字符），按自然段分批送入 LLM，避免单次输出超过 max_tokens 导致 JSON 截断
        max_batch_chars = 4000
        if len(text) > max_batch_chars:
            segments: list[str] = []
            paragraphs = [p for p in text.split("\n\n") if p.strip()]

            # 防御极端长段落（如无双换行文章）：展开超过上限的单个自然段
            flat_paragraphs: list[str] = []
            for p in paragraphs:
                if len(p) > max_batch_chars:
                    sub_lines = [line for line in p.split("\n") if line.strip()]
                    for line in sub_lines:
                        if len(line) > max_batch_chars:
                            for k in range(0, len(line), max_batch_chars):
                                flat_paragraphs.append(line[k : k + max_batch_chars])
                        else:
                            flat_paragraphs.append(line)
                else:
                    flat_paragraphs.append(p)

            current_seg: list[str] = []
            current_len = 0
            for p in flat_paragraphs:
                if current_len + len(p) > max_batch_chars and current_seg:
                    segments.append("\n\n".join(current_seg))
                    current_seg = [p]
                    current_len = len(p)
                else:
                    current_seg.append(p)
                    current_len += len(p)
            if current_seg:
                segments.append("\n\n".join(current_seg))
        else:
            segments = [text]

        results: list[Chunk] = []
        chunk_idx = 0
        for seg in segments:
            seg_chunks = await self._chunk_single_segment(seg, doc_id, config, chunk_idx)
            results.extend(seg_chunks)
            chunk_idx += len(seg_chunks)

        if not results:
            # 优雅降级：若 LLM 失败或模型返回空，自动降级为 RecursiveChunker 兜底
            from app.document.chunker.recursive import RecursiveChunker

            logger.warning(
                "llm chunker produced empty result, falling back to recursive chunker",
                doc_id=doc_id,
            )
            return await RecursiveChunker().chunk(text, doc_id, config)

        logger.debug("llm chunker completed", doc_id=doc_id, count=len(results))
        return results

    async def _chunk_single_segment(
        self, seg_text: str, doc_id: str, config: ChunkConfig, start_index: int
    ) -> list[Chunk]:
        from app.common.jinja import jinja_env
        from app.common.llm_client import get_chat_client, llm_breaker
        from app.config import get_settings as _get_settings

        settings = _get_settings()
        client = get_chat_client()
        template = jinja_env.get_template("document_llm_split.j2")
        prompt = template.render(source_text=seg_text)

        try:
            async with llm_breaker():
                resp = await client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            content = (resp.choices[0].message.content or "").strip()
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

            seg_results: list[Chunk] = []
            for i, item in enumerate(items):
                if isinstance(item, str):
                    txt = item.strip()
                elif isinstance(item, dict):
                    txt = item.get("content", "").strip()
                else:
                    continue
                if not txt or len(txt) < config.min_chunk_size:
                    continue
                seg_results.append(
                    Chunk(
                        chunk_id=next_id_str(),
                        doc_id=doc_id,
                        content=txt,
                        chunk_index=start_index + i,
                        chunk_type="child",
                        token_count=count_tokens(txt),
                    )
                )
            return seg_results
        except Exception as e:
            logger.warning("llm chunk segment failed", doc_id=doc_id, error=str(e))
            return []
