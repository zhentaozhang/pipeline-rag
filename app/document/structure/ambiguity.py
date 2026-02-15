import json

import structlog

from app.common.jinja import jinja_env as _JINJA
from app.common.llm_client import get_chat_client, llm_breaker
from app.config import get_settings
from app.document.structure.models import DocumentStructureSignal, DocumentStructureSignalKind

logger = structlog.get_logger(__name__)


class DocumentStructureAmbiguityResolver:
    """消除文档结构信号中的歧义（依赖 LLM）"""

    def __init__(self) -> None:
        self.properties = get_settings().structure
        settings = get_settings()
        self._openai = get_chat_client()
        self.model = settings.llm.model

    async def resolve(
        self,
        document_title: str,
        all_lines: list[str],
        source_signals: list[DocumentStructureSignal],
    ) -> list[DocumentStructureSignal]:

        if not source_signals:
            return []

        if not self.properties.llm_disambiguation_enabled:
            return source_signals

        ambiguous_signals = []
        for s in source_signals:
            if (
                s.is_ambiguous
                and self.properties.ambiguity_confidence_floor
                <= s.confidence
                <= self.properties.ambiguity_confidence_ceil
            ):
                ambiguous_signals.append(s)
                if len(ambiguous_signals) >= max(1, self.properties.max_ambiguous_signals_per_call):
                    break

        if not ambiguous_signals:
            return source_signals

        try:
            prompt = self._build_prompt(document_title, ambiguous_signals, all_lines)
            async with llm_breaker():
                response = await self._openai.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                    if "dashscope" not in str(self._openai.base_url)
                    else None,
                )
            content = response.choices[0].message.content
            results = self._parse_json_result(content)

            if not results:
                return source_signals

            result_map = {r["line_no"]: r for r in results if r.get("line_no") is not None}

            merged = []
            for signal in source_signals:
                resolved = result_map.get(signal.line_no)
                merged.append(self._apply_result(signal, resolved))

            return merged
        except Exception as e:
            logger.warning("结构歧义判定失败，回退到规则结果", error=str(e), exc_info=True)
            return source_signals

    def _build_prompt(
        self,
        document_title: str,
        ambiguous_signals: list[DocumentStructureSignal],
        all_lines: list[str],
    ) -> str:
        blocks = self._build_candidate_blocks(ambiguous_signals, all_lines)
        template = _JINJA.get_template("structure_parse.j2")
        return template.render(
            document_title=document_title or "未命名文档", candidate_blocks=blocks
        )

    def _build_candidate_blocks(
        self, ambiguous_signals: list[DocumentStructureSignal], all_lines: list[str]
    ) -> str:
        safe_lines = all_lines or []
        context_window = max(1, self.properties.context_window_lines)
        template = _JINJA.get_template("structure_parse_candidate.j2")

        blocks = []
        for signal in ambiguous_signals:
            current_index = max(0, signal.line_no - 1)
            start = max(0, current_index - context_window)
            end = min(len(safe_lines) - 1, current_index + context_window)

            context_builder = []
            for i in range(start, end + 1):
                prefix = ">> " if i + 1 == signal.line_no else "   "
                context_builder.append(f"{prefix}{i + 1}: {safe_lines[i] or ''}")

            block = template.render(
                line_no=signal.line_no,
                context_lines="\n".join(context_builder),
                initial_kind=signal.kind.value,
                initial_title=signal.title,
                initial_code=signal.node_code,
            )
            blocks.append(block)

        return "\n\n".join(blocks).strip()

    def _parse_json_result(self, content: str) -> list[dict]:
        if not content:
            return []
        normalized = content.strip()
        start = normalized.find("[")
        end = normalized.rfind("]")
        if start < 0 or end <= start:
            return []

        json_array = normalized[start : end + 1]
        try:
            return json.loads(json_array)
        except json.JSONDecodeError:
            return []

    def _apply_result(
        self, source: DocumentStructureSignal, resolved: dict | None
    ) -> DocumentStructureSignal:
        if not resolved or not resolved.get("resolved_kind"):
            return source

        target_kind_str = str(resolved["resolved_kind"]).strip().upper()
        if target_kind_str == "HEADING":
            target_kind = DocumentStructureSignalKind.HEADING
        elif target_kind_str == "LIST_ITEM":
            target_kind = DocumentStructureSignalKind.LIST_ITEM
        else:
            target_kind = DocumentStructureSignalKind.BODY

        source.kind = target_kind

        if target_kind == DocumentStructureSignalKind.HEADING:
            level_hint = resolved.get("level_hint")
            if isinstance(level_hint, int) and level_hint > 0:
                source.level_hint = level_hint

        source.reasons.append("llm-disambiguated")
        source.confidence = max(source.confidence, 0.88)
        return source
