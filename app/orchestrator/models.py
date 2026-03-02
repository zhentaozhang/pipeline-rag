import decimal
from dataclasses import dataclass, field


@dataclass
class RouteQueryContext:
    question: str
    rewrite_question: str
    routing_text: str
    query_terms: list[str]
    query_embedding: list[float] | None = None


@dataclass
class ScopeRouteCandidate:
    scope_code: str
    scope_name: str
    score: decimal.Decimal
    reason: str


@dataclass
class TopicRouteCandidate:
    topic_code: str
    topic_name: str
    scope_code: str
    score: decimal.Decimal
    reason: str


@dataclass
class DocumentRouteCandidate:
    document_id: str
    document_name: str
    last_index_task_id: str
    scope_code: str
    scope_name: str
    business_category: str
    document_tags: str
    score: decimal.Decimal
    reason: str


@dataclass
class KnowledgeRouteDecision:
    scopes: list[ScopeRouteCandidate] = field(default_factory=list)
    topics: list[TopicRouteCandidate] = field(default_factory=list)
    documents: list[DocumentRouteCandidate] = field(default_factory=list)
    confidence: decimal.Decimal = decimal.Decimal("0.0")
    route_status: str = "FAILED"
    reason: str = ""

    def top_document(self) -> DocumentRouteCandidate | None:
        if not self.documents:
            return None
        return self.documents[0]


@dataclass
class DocumentRouteDecision:
    """面向执行器的路由决策"""

    execution_mode: str = "RETRIEVAL"
    doc_ids: list[str] = field(default_factory=list)
    clarification_reply: str = ""
    clarification_options: list[str] = field(default_factory=list)
