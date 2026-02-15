from collections import deque
from typing import NamedTuple

from app.document.structure.models import (
    DocumentStructureNodeDraft,
    DocumentStructureNodeType,
    DocumentStructureSignal,
    DocumentStructureSignalKind,
)


class ListContext(NamedTuple):
    node: DocumentStructureNodeDraft
    indent_level: int


class DocumentStructureHierarchyResolver:
    """将线性结构信号还原为层级结构树"""

    def resolve(
        self, document_title: str, signals: list[DocumentStructureSignal]
    ) -> list[DocumentStructureNodeDraft]:

        drafts: list[DocumentStructureNodeDraft] = []

        root = DocumentStructureNodeDraft(
            node_no=1,
            line_no=0,
            node_type=DocumentStructureNodeType.DOCUMENT.value,
            parent_node_no=None,
            depth=0,
            node_code="",
            title=document_title or "文档",
            anchor_text=document_title or "文档",
            canonical_path="/document",
            section_path="",
            source_family="document",
            confidence=1.0,
        )
        drafts.append(root)

        next_node_no = 2
        current_section: DocumentStructureNodeDraft | None = root
        current_list_item: DocumentStructureNodeDraft | None = None
        list_stack: deque[ListContext] = deque()
        latest_heading_by_depth: dict[int, int] = {}
        latest_heading_by_numeric_path: dict[str, int] = {}

        for signal in signals:
            if not signal or signal.line_no == 0:
                continue

            if signal.kind == DocumentStructureSignalKind.BLANK:
                current_list_item = None
                list_stack.clear()
            elif signal.kind == DocumentStructureSignalKind.NOISE:
                pass
            elif signal.kind in (
                DocumentStructureSignalKind.TABLE_ROW,
                DocumentStructureSignalKind.QUOTE,
                DocumentStructureSignalKind.BODY,
            ):
                self._append_body(signal, current_section, current_list_item, root)
            elif signal.kind in (
                DocumentStructureSignalKind.STEP_ITEM,
                DocumentStructureSignalKind.LIST_ITEM,
            ):
                list_parent = self._resolve_list_parent(
                    signal, current_section or root, list_stack, root
                )
                list_node = self._build_list_node(signal, next_node_no, list_parent)
                next_node_no += 1
                drafts.append(list_node)
                current_list_item = list_node
                self._register_list_context(signal, list_node, list_stack)
                if current_section:
                    current_section.append_line(signal.normalized_text)
            elif signal.kind in (
                DocumentStructureSignalKind.HEADING,
                DocumentStructureSignalKind.HEADING_CANDIDATE,
            ):
                heading_node = self._build_heading_node(
                    signal,
                    next_node_no,
                    drafts,
                    latest_heading_by_depth,
                    latest_heading_by_numeric_path,
                )
                next_node_no += 1
                drafts.append(heading_node)
                current_section = heading_node
                current_list_item = None
                list_stack.clear()
            else:
                self._append_body(signal, current_section, current_list_item, root)

        drafts.sort(key=lambda x: x.node_no)
        return drafts

    def _append_body(
        self,
        signal: DocumentStructureSignal,
        current_section: DocumentStructureNodeDraft | None,
        current_list_item: DocumentStructureNodeDraft | None,
        root: DocumentStructureNodeDraft,
    ):
        line = signal.normalized_text if signal else ""
        if not line:
            return

        target = current_list_item if current_list_item else (current_section or root)
        target.append_line(line)

        if (
            current_list_item
            and current_section
            and current_section.node_no != current_list_item.node_no
        ):
            current_section.append_line(line)

        if not current_section and target != root:
            root.append_line(line)

    def _build_list_node(
        self,
        signal: DocumentStructureSignal,
        node_no: int,
        parent: DocumentStructureNodeDraft | None,
    ) -> DocumentStructureNodeDraft:

        node_type = (
            DocumentStructureNodeType.STEP.value
            if signal.kind == DocumentStructureSignalKind.STEP_ITEM
            else DocumentStructureNodeType.LIST_ITEM.value
        )
        parent_no = parent.node_no if parent else 1
        depth = (parent.depth if parent else 0) + 1
        node_code = signal.node_code or (
            str(signal.item_index) if signal.item_index is not None else ""
        )
        source_family = "step" if signal.kind == DocumentStructureSignalKind.STEP_ITEM else "list"

        draft = DocumentStructureNodeDraft(
            node_no=node_no,
            line_no=signal.line_no,
            node_type=node_type,
            parent_node_no=parent_no,
            depth=depth,
            node_code=node_code,
            title=signal.title,
            anchor_text=signal.normalized_text or signal.title,
            item_index=signal.item_index,
            source_family=source_family,
            confidence=signal.confidence,
        )
        draft.append_line(signal.normalized_text)
        return draft

    def _resolve_list_parent(
        self,
        signal: DocumentStructureSignal,
        current_section: DocumentStructureNodeDraft,
        list_stack: deque[ListContext],
        root: DocumentStructureNodeDraft,
    ) -> DocumentStructureNodeDraft:

        indent_level = self._safe_indent_level(signal)
        while list_stack and list_stack[-1].indent_level >= indent_level:
            list_stack.pop()

        if list_stack and indent_level > list_stack[-1].indent_level:
            return list_stack[-1].node

        return current_section or root

    def _register_list_context(
        self,
        signal: DocumentStructureSignal,
        list_node: DocumentStructureNodeDraft,
        list_stack: deque[ListContext],
    ):
        indent_level = self._safe_indent_level(signal)
        while list_stack and list_stack[-1].indent_level >= indent_level:
            list_stack.pop()
        list_stack.append(ListContext(node=list_node, indent_level=indent_level))

    def _build_heading_node(
        self,
        signal: DocumentStructureSignal,
        node_no: int,
        drafts: list[DocumentStructureNodeDraft],
        latest_heading_by_depth: dict[int, int],
        latest_heading_by_numeric_path: dict[str, int],
    ) -> DocumentStructureNodeDraft:

        depth = self._resolve_heading_depth(
            signal, drafts, latest_heading_by_depth, latest_heading_by_numeric_path
        )
        parent_node_no = self._resolve_heading_parent_node_no(
            signal, depth, latest_heading_by_depth, latest_heading_by_numeric_path
        )

        draft = DocumentStructureNodeDraft(
            node_no=node_no,
            line_no=signal.line_no,
            node_type=DocumentStructureNodeType.SECTION.value,
            parent_node_no=parent_node_no,
            depth=depth,
            node_code=signal.node_code or "",
            title=signal.title,
            anchor_text=self._build_heading_anchor_text(signal),
            numeric_path=list(signal.numeric_path) if signal.numeric_path else [],
            source_family=self._resolve_heading_family(signal),
            confidence=signal.confidence,
        )
        draft.append_line(signal.normalized_text)

        to_remove = [k for k in latest_heading_by_depth if k >= depth]
        for k in to_remove:
            del latest_heading_by_depth[k]
        latest_heading_by_depth[depth] = node_no

        numeric_key = self._numeric_key(draft.numeric_path)
        if numeric_key:
            latest_heading_by_numeric_path[numeric_key] = node_no

        return draft

    def _resolve_heading_depth(
        self,
        signal: DocumentStructureSignal,
        drafts: list[DocumentStructureNodeDraft],
        latest_heading_by_depth: dict[int, int],
        latest_heading_by_numeric_path: dict[str, int],
    ) -> int:
        family = self._resolve_heading_family(signal)
        numeric_path = signal.numeric_path or []

        if family == "markdown":
            return max(1, self._safe_level(signal.level_hint, 1))
        if family in ("chapter", "appendix"):
            return 1
        if family == "decimal":
            if len(numeric_path) <= 1:
                return 1
            parent_no = latest_heading_by_numeric_path.get(self._numeric_key(numeric_path[:-1]))
            if parent_no:
                parent = self._find_by_node_no(drafts, parent_no)
                if parent:
                    return parent.depth + 1
            chapter_parent = latest_heading_by_numeric_path.get(
                self._numeric_key([numeric_path[0]])
            )
            if chapter_parent:
                parent = self._find_by_node_no(drafts, chapter_parent)
                if parent:
                    return parent.depth + 1
            return len(numeric_path)

        return max(1, self._safe_level(signal.level_hint, 1))

    def _resolve_heading_parent_node_no(
        self,
        signal: DocumentStructureSignal,
        depth: int,
        latest_heading_by_depth: dict[int, int],
        latest_heading_by_numeric_path: dict[str, int],
    ) -> int:
        family = self._resolve_heading_family(signal)
        numeric_path = signal.numeric_path or []

        if family in ("chapter", "appendix"):
            return 1

        if family == "decimal" and len(numeric_path) > 1:
            exact_parent = latest_heading_by_numeric_path.get(self._numeric_key(numeric_path[:-1]))
            if exact_parent:
                return exact_parent
            chapter_parent = latest_heading_by_numeric_path.get(
                self._numeric_key([numeric_path[0]])
            )
            if chapter_parent:
                return chapter_parent

        return self._find_nearest_parent_by_depth(depth, latest_heading_by_depth)

    def _find_nearest_parent_by_depth(
        self, depth: int, latest_heading_by_depth: dict[int, int]
    ) -> int:
        for candidate_depth in range(depth - 1, 0, -1):
            parent_no = latest_heading_by_depth.get(candidate_depth)
            if parent_no:
                return parent_no
        return 1

    def _resolve_heading_family(self, signal: DocumentStructureSignal) -> str:
        if not signal or not signal.reasons:
            return "plain"
        reasons = signal.reasons
        if "markdown-heading" in reasons:
            return "markdown"
        if "chapter-heading" in reasons:
            return "chapter"
        if "appendix-heading" in reasons:
            return "appendix"
        if "decimal-heading" in reasons:
            return "decimal"
        if "single-digit-ambiguous-heading" in reasons:
            return "decimal"
        return "plain"

    def _build_heading_anchor_text(self, signal: DocumentStructureSignal) -> str:
        code = (signal.node_code or "").strip()
        title = (signal.title or "").strip()
        if not code:
            return title
        if title.startswith(code):
            return title
        return f"{code} {title}"

    def _numeric_key(self, numeric_path: list[int]) -> str:
        if not numeric_path:
            return ""
        return ".".join(str(p) for p in numeric_path)

    def _safe_level(self, level_hint: int | None, default_value: int) -> int:
        if level_hint is None or level_hint <= 0:
            return default_value
        return level_hint

    def _safe_indent_level(self, signal: DocumentStructureSignal) -> int:
        if signal.indent_level is None or signal.indent_level < 0:
            return 0
        return signal.indent_level

    def _find_by_node_no(
        self, drafts: list[DocumentStructureNodeDraft], node_no: int
    ) -> DocumentStructureNodeDraft | None:
        for draft in drafts:
            if draft.node_no == node_no:
                return draft
        return None
