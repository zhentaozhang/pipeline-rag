
import pytest

import app.rag.graph.composite_graph_service as composite_module
from app.rag.graph.composite_graph_service import CompositeGraphService


class FakeNeo4j:
    def __init__(self, available=True, error=None):
        self.available = available
        self.error = error
        self.calls = []

    async def is_graph_available(self, doc_id):
        self.calls.append(("is_graph_available", doc_id))
        if self.error:
            raise self.error
        return self.available

    async def get_document_tree(self, doc_id):
        self.calls.append(("get_document_tree", doc_id))
        return "neo4j tree"


class FakeMysql:
    def __init__(self):
        self.calls = []

    async def get_document_tree(self, doc_id):
        self.calls.append(("get_document_tree", doc_id))
        return "mysql tree"

    async def find_section_by_id(self, doc_id, section_node_id):
        self.calls.append(("find_section_by_id", doc_id, section_node_id))
        return "mysql section"


@pytest.fixture
def services(monkeypatch):
    holder = {"neo4j": None, "mysql": None}

    def install(available=True, error=None):
        holder["neo4j"] = FakeNeo4j(available=available, error=error)
        holder["mysql"] = FakeMysql()
        monkeypatch.setattr(
            composite_module, "Neo4jGraphService", lambda: holder["neo4j"]
        )
        monkeypatch.setattr(composite_module, "MysqlGraphService", lambda: holder["mysql"])
        return CompositeGraphService(), holder

    return install


class TestDelegate:
    @pytest.mark.asyncio
    async def test_neo4j_when_available(self, services):
        svc, holder = services(available=True)
        delegated = await svc._delegate("doc1")
        assert delegated is holder["neo4j"]

    @pytest.mark.asyncio
    async def test_mysql_when_unavailable(self, services):
        svc, holder = services(available=False)
        delegated = await svc._delegate("doc1")
        assert delegated is holder["mysql"]

    @pytest.mark.asyncio
    async def test_mysql_when_error(self, services):
        svc, holder = services(available=True, error=RuntimeError("neo4j down"))
        delegated = await svc._delegate("doc1")
        assert delegated is holder["mysql"]

    @pytest.mark.asyncio
    async def test_is_graph_available_direct(self, services):
        svc, holder = services(available=True)
        assert await svc.is_graph_available("doc1") is True
        assert holder["neo4j"].calls == [("is_graph_available", "doc1")]


class TestDelegatedMethods:
    @pytest.mark.asyncio
    async def test_get_document_tree_neo4j(self, services):
        svc, holder = services(available=True)
        assert await svc.get_document_tree("doc1") == "neo4j tree"

    @pytest.mark.asyncio
    async def test_get_document_tree_fallback(self, services):
        svc, holder = services(available=False)
        assert await svc.get_document_tree("doc1") == "mysql tree"

    @pytest.mark.asyncio
    async def test_find_section_by_id_fallback(self, services):
        svc, holder = services(available=False)
        out = await svc.find_section_by_id("doc1", "7")
        assert out == "mysql section"
        assert holder["mysql"].calls == [("find_section_by_id", "doc1", "7")]
