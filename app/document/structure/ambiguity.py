import json

import structlog

from app.common.jinja import jinja_env as _JINJA
from app.common.llm_client import get_chat_client, llm_breaker
from app.config import get_settings
from app.document.structure.models import DocumentStructureSignal, DocumentStructureSignalKind

logger = structlog.get_logger(__name__)

# JEV 结构歧义：归类选项 + 层级等级（有序 → Score）
_JEV_KIND_OPTIONS = {
    "heading": "章节标题：用于分节、概括性的短标题，通常不是可执行动作（如“第一章 概述”“1.2 系统架构”“关于我们”）",
    "list_item": "列表项或操作步骤：可执行动作或枚举条目（如“1. 打开配置文件”“- 检查依赖”“步骤一：安装”“（1）提交申请”）",
    "body": "正文段落：用完整句子陈述信息的普通内容，既不是标题也不是清单项",
}
_JEV_KIND_TO_SIGNAL = {
    "heading": "HEADING",
    "list_item": "LIST_ITEM",
    "body": "BODY",
}
_JEV_LEVELS = ["一级标题", "二级标题", "三级标题", "四级标题", "五级标题"]


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

        # JEV System 1 优先：Choice（归类）+ Score（层级），一次请求并行判定，去 LLM
        jev_cfg = getattr(get_settings(), "jev", None)
        if jev_cfg and getattr(jev_cfg, "structure_ambiguity_enabled", True):
            try:
                return await self._resolve_via_jev(all_lines, source_signals, ambiguous_signals)
            except Exception as e:
                logger.warning("JEV 结构歧义判定失败，回退 LLM", error=str(e)[:120])

        try:
            prompt = self._build_prompt(document_title, ambiguous_signals, all_lines)
            async with llm_breaker():
                response = await self._openai.chat.completions.create(  # type: ignore[call-overload]
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

    async def _resolve_via_jev(
        self,
        all_lines: list[str],
        source_signals: list[DocumentStructureSignal],
        ambiguous_signals: list[DocumentStructureSignal],
    ) -> list[DocumentStructureSignal]:
        """用 JEV Choice（归类）+ Score（层级）一次性判定全部歧义行。

        所有歧义块的上下文拼成一个 state，每个块两个问题（kind/level），
        单次请求并行判定；空/缺字段则抛错由调用方回退 LLM。
        """
        from app.infra.jev_client import get_jev_client

        state = self._build_jev_state(ambiguous_signals, all_lines)
        questions: dict[str, dict] = {}
        for s in ambiguous_signals:
            questions[f"kind_{s.line_no}"] = {
                "type": "choice",
                "instructions": (
                    f"候选块（第 {s.line_no} 行，用 >> 标记）在文档结构层级中应归类为？"
                ),
                "options": _JEV_KIND_OPTIONS,
            }
            questions[f"level_{s.line_no}"] = {
                "type": "score",
                "instructions": (
                    f"若第 {s.line_no} 行是标题，它是第几级标题（越靠前级别越高）？"
                    "非标题可忽略本题。"
                ),
                "levels": _JEV_LEVELS,
            }

        answers = await get_jev_client().system_one(state=state, questions=questions)
        if not answers:
            raise ValueError("JEV returned empty answers")

        resolved_map: dict[int, dict] = {}
        for s in ambiguous_signals:
            kind_ans = answers.get(f"kind_{s.line_no}")
            if not isinstance(kind_ans, dict) or "choice" not in kind_ans:
                raise ValueError(f"JEV missing kind for line {s.line_no}")
            kind = kind_ans["choice"]
            if kind not in _JEV_KIND_TO_SIGNAL:
                raise ValueError(f"JEV unexpected kind={kind}")

            level_hint = None
            if kind == "heading":
                level_ans = answers.get(f"level_{s.line_no}")
                if isinstance(level_ans, dict) and level_ans.get("score") in _JEV_LEVELS:
                    level_hint = _JEV_LEVELS.index(level_ans["score"]) + 1
            resolved_map[s.line_no] = {
                "resolved_kind": _JEV_KIND_TO_SIGNAL[kind],
                "level_hint": level_hint,
            }

        return [self._apply_result(sig, resolved_map.get(sig.line_no)) for sig in source_signals]

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

    def _build_jev_state(
        self, ambiguous_signals: list[DocumentStructureSignal], all_lines: list[str]
    ) -> str:
        """构建 JEV 用的中性上下文（不带 `初始判断` 等偏置字段，避免模型被初始类别带偏）。"""
        safe_lines = all_lines or []
        context_window = max(1, self.properties.context_window_lines)
        blocks = []
        for signal in ambiguous_signals:
            current_index = max(0, signal.line_no - 1)
            start = max(0, current_index - context_window)
            end = min(len(safe_lines) - 1, current_index + context_window)
            lines = []
            for i in range(start, end + 1):
                prefix = ">> " if i + 1 == signal.line_no else "   "
                lines.append(f"{prefix}{i + 1}: {safe_lines[i] or ''}")
            blocks.append(f"### 候选行 {signal.line_no}\n" + "\n".join(lines))
        return "\n\n".join(blocks).strip()

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
            parsed = json.loads(json_array)
            return parsed if isinstance(parsed, list) else []
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
