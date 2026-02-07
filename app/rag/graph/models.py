"""
Graph 查询结果模型
"""

from typing import Any

from pydantic import BaseModel, Field


class GraphItem(BaseModel):
    node_id: int = Field(alias="nodeId")
    document_id: int = Field(alias="documentId")
    parse_task_id: int | None = Field(default=None, alias="parseTaskId")
    node_no: int | None = Field(default=None, alias="nodeNo")
    node_type: str | None = None
    section_node_id: int | None = Field(default=None, alias="sectionNodeId")
    prev_sibling_node_id: int | None = Field(default=None, alias="prevSiblingNodeId")
    next_sibling_node_id: int | None = Field(default=None, alias="nextSiblingNodeId")
    title: str | None = None
    anchor_text: str | None = Field(default=None, alias="anchorText")
    section_path: str | None = Field(default=None, alias="sectionPath")
    canonical_path: str | None = Field(default=None, alias="canonicalPath")
    content_text: str | None = Field(default=None, alias="contentText")
    item_index: int | None = Field(default=None, alias="itemIndex")

    model_config = {"populate_by_name": True}

    def display_text(self) -> str:
        return self.content_text or self.anchor_text or self.title or ""


class GraphSection(BaseModel):
    node_id: int = Field(alias="nodeId")
    document_id: int = Field(alias="documentId")
    parse_task_id: int | None = Field(default=None, alias="parseTaskId")
    node_no: int | None = Field(default=None, alias="nodeNo")
    depth: int | None = Field(default=None)
    parent_node_id: int | None = Field(default=None, alias="parentNodeId")
    prev_sibling_node_id: int | None = Field(default=None, alias="prevSiblingNodeId")
    next_sibling_node_id: int | None = Field(default=None, alias="nextSiblingNodeId")
    node_code: str | None = Field(default=None, alias="nodeCode")
    title: str | None = None
    anchor_text: str | None = Field(default=None, alias="anchorText")
    section_path: str | None = Field(default=None, alias="sectionPath")
    canonical_path: str | None = Field(default=None, alias="canonicalPath")
    content_text: str | None = Field(default=None, alias="contentText")

    model_config = {"populate_by_name": True}

    def display_title(self) -> str:
        if self.section_path:
            return self.section_path.strip()
        if self.node_code and self.title:
            return f"{self.node_code} {self.title}".strip()
        return self.title or ""


class GraphSectionWithSiblings(BaseModel):
    section: GraphSection | None = None
    parent: GraphSection | None = None
    previous_sibling: GraphSection | None = Field(default=None, alias="previousSibling")
    next_sibling: GraphSection | None = Field(default=None, alias="nextSibling")

    model_config = {"populate_by_name": True}


class GraphSectionWithChildren(BaseModel):
    section: GraphSection | None = None
    children: list[GraphSection] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class GraphItemWithContext(BaseModel):
    section: GraphSection | None = None
    item: GraphItem | None = None
    sibling_items: list[GraphItem] = Field(default_factory=list, alias="siblingItems")

    model_config = {"populate_by_name": True}


class GraphQueryResult(BaseModel):
    doc: dict[str, Any] = Field(default_factory=dict)
    sections: list[GraphSection] = Field(default_factory=list)
    target_section: GraphSection | None = Field(default=None, alias="targetSection")
    parent_section: GraphSection | None = Field(default=None, alias="parentSection")
    prev_sibling: GraphSection | None = Field(default=None, alias="previousSibling")
    next_sibling: GraphSection | None = Field(default=None, alias="nextSibling")
    children: list[GraphSection] = Field(default_factory=list)
    all_items: list[GraphItem] = Field(default_factory=list, alias="allItems")
    target_item: GraphItem | None = Field(default=None, alias="targetItem")
    matched_items: list[GraphItem] = Field(default_factory=list, alias="matchedItems")

    model_config = {"populate_by_name": True}
