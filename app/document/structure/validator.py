import re
from collections import defaultdict

from app.document.structure.models import DocumentStructureNodeCandidate, DocumentStructureNodeDraft


class DocumentStructureTreeValidator:
    """验证并修复生成的文档树结构"""

    def validate_and_build(
        self, document_title: str, drafts: list[DocumentStructureNodeDraft]
    ) -> list[DocumentStructureNodeCandidate]:
        if not drafts:
            return []

        draft_map = {d.node_no: d for d in drafts if d and d.node_no is not None}

        self._collapse_synthetic_title_section(document_title, draft_map)
        self._repair_numbered_hierarchy(draft_map)
        self._repair_invalid_parents(draft_map)
        self._recompute_depths(draft_map)
        self._rebuild_paths(document_title, draft_map)
        self._rebuild_sibling_links(draft_map)

        ordered = sorted(draft_map.values(), key=lambda x: x.node_no)
        return [self._to_candidate(draft) for draft in ordered]

    def _collapse_synthetic_title_section(
        self, document_title: str, draft_map: dict[int, DocumentStructureNodeDraft]
    ):
        normalized_title = self._normalize_comparable_title(document_title)
        if not normalized_title:
            return

        duplicate_node_no = None
        for draft in draft_map.values():
            if (
                not draft
                or draft.node_no == 1
                or not draft.is_section
                or draft.parent_node_no != 1
                or draft.node_code
            ):
                continue
            if normalized_title == self._normalize_comparable_title(draft.title):
                duplicate_node_no = draft.node_no
                break

        if duplicate_node_no is None:
            return

        for draft in draft_map.values():
            if draft and draft.parent_node_no == duplicate_node_no:
                draft.parent_node_no = 1

        draft_map.pop(duplicate_node_no, None)

    def _repair_numbered_hierarchy(self, draft_map: dict[int, DocumentStructureNodeDraft]):
        numeric_path_map = {}
        for draft in draft_map.values():
            if draft and draft.is_section:
                key = self._numeric_key(draft.numeric_path)
                if key and key not in numeric_path_map:
                    numeric_path_map[key] = draft.node_no

        for draft in draft_map.values():
            if not draft or not draft.is_section:
                continue
            numeric_path = draft.numeric_path
            if not numeric_path:
                continue
            if len(numeric_path) == 1:
                draft.parent_node_no = 1
                continue

            direct_parent_key = self._numeric_key(numeric_path[:-1])
            direct_parent = numeric_path_map.get(direct_parent_key)
            if direct_parent:
                draft.parent_node_no = direct_parent
                continue

            chapter_parent_key = self._numeric_key([numeric_path[0]])
            chapter_parent = numeric_path_map.get(chapter_parent_key)
            if chapter_parent:
                draft.parent_node_no = chapter_parent

    def _repair_invalid_parents(self, draft_map: dict[int, DocumentStructureNodeDraft]):
        for draft in draft_map.values():
            if not draft or draft.node_no == 1:
                continue
            parent = (
                draft_map.get(draft.parent_node_no) if draft.parent_node_no is not None else None
            )
            if not parent:
                draft.parent_node_no = 1
                continue
            if draft.is_section and parent.is_list_like:
                draft.parent_node_no = (
                    parent.parent_node_no if parent.parent_node_no is not None else 1
                )

    def _recompute_depths(self, draft_map: dict[int, DocumentStructureNodeDraft]):
        root = draft_map.get(1)
        if not root:
            return
        root.depth = 0
        ordered = sorted(draft_map.values(), key=lambda x: x.node_no)
        for draft in ordered:
            if not draft or draft.node_no == 1:
                continue
            parent = (
                draft_map.get(draft.parent_node_no) if draft.parent_node_no is not None else None
            )
            draft.depth = (parent.depth + 1) if parent else 1

    def _rebuild_paths(self, document_title: str, draft_map: dict[int, DocumentStructureNodeDraft]):
        for draft in draft_map.values():
            if not draft:
                continue
            if draft.node_no == 1:
                draft.canonical_path = "/document"
                draft.section_path = ""
                continue

            parent = (
                draft_map.get(draft.parent_node_no) if draft.parent_node_no is not None else None
            )
            parent_canonical_path = (
                parent.canonical_path if parent and parent.canonical_path else "/document"
            )
            parent_section_path = parent.section_path if parent and parent.section_path else ""
            segment = self._build_path_segment(draft)

            draft.canonical_path = f"{parent_canonical_path}/{segment}"
            if draft.is_section:
                draft.section_path = self._join_section_path(
                    parent_section_path, self._display_title(draft)
                )
            else:
                draft.section_path = parent_section_path

    def _rebuild_sibling_links(self, draft_map: dict[int, DocumentStructureNodeDraft]):
        children_by_parent = defaultdict(list)
        for draft in draft_map.values():
            if draft and draft.node_no != 1:
                children_by_parent[draft.parent_node_no].append(draft)

        for siblings in children_by_parent.values():
            siblings.sort(key=lambda x: x.line_no)
            for index, current in enumerate(siblings):
                current.prev_sibling_node_no = siblings[index - 1].node_no if index > 0 else 0
                current.next_sibling_node_no = (
                    siblings[index + 1].node_no if index < len(siblings) - 1 else 0
                )

    def _to_candidate(self, draft: DocumentStructureNodeDraft) -> DocumentStructureNodeCandidate:
        return DocumentStructureNodeCandidate(
            node_no=draft.node_no,
            node_type=draft.node_type,
            parent_node_no=draft.parent_node_no,
            prev_sibling_node_no=self._normalize_sibling(draft.prev_sibling_node_no),
            next_sibling_node_no=self._normalize_sibling(draft.next_sibling_node_no),
            depth=draft.depth,
            node_code=draft.node_code,
            title=draft.title,
            anchor_text=draft.anchor_text,
            canonical_path=draft.canonical_path or "",
            section_path=draft.section_path or "",
            content_text=draft.content_text(),
            item_index=draft.item_index,
        )

    def _normalize_sibling(self, sibling_node_no: int | None) -> int:
        return sibling_node_no if sibling_node_no is not None else 0

    def _join_section_path(self, parent_section_path: str, current_title: str) -> str:
        if not parent_section_path:
            return current_title or ""
        if not current_title:
            return parent_section_path
        return f"{parent_section_path} > {current_title}"

    def _build_path_segment(self, draft: DocumentStructureNodeDraft) -> str:
        if not draft:
            return "node"
        if draft.is_list_like:
            if draft.item_index and draft.item_index > 0:
                return f"item-{draft.item_index}"
            return self._slug(self._display_title(draft))

        code = (draft.node_code or "").strip()
        if code:
            return self._slug(code)
        return self._slug(self._display_title(draft))

    def _display_title(self, draft: DocumentStructureNodeDraft) -> str:
        code = (draft.node_code or "").strip()
        title = (draft.title or "").strip()
        if not code:
            return title
        if title.startswith(code):
            return title
        return f"{code} {title}"

    def _slug(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return "node"
        slug = re.sub(r"\s+", "-", normalized)
        # Python covers CJK Unified + Ext A/B/C/D/E/F
        slug = re.sub(
            r"[^\w\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002A6DF\U0002A700-\U0002B73F\U0002B740-\U0002B81F\U0002B820-\U0002CEAF\U0002CEB0-\U0002EBEF.-]",
            "",
            slug,
        )
        return slug if slug else "node"

    def _numeric_key(self, numeric_path: list[int]) -> str:
        if not numeric_path:
            return ""
        return ".".join(str(p) for p in numeric_path)

    def _normalize_comparable_title(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return ""
        normalized = re.sub(r"^#+\s*", "", normalized)
        normalized = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.lower()
