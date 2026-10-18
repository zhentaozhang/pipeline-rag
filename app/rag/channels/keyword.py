"""
关键词检索通道（Elasticsearch + IK 分词）

使用 match_phrase + multi_match (BestFields) 查询，
IK 分词器处理中文，相对阈值过滤弱命中（score < top_score * keyword_relative_score_floor）
"""

from typing import Any

import structlog

from app.chat.schema import Evidence, SubQuestion
from app.common.text_utils import normalize_step_numeral
from app.common.utils import safe_int
from app.config import get_settings
from app.infra.es import CHUNK_INDEX, get_es
from app.rag.evidence_meta import leaf_section_title

logger = structlog.get_logger(__name__)
settings = get_settings()


class KeywordRetrievalChannel:
    """
    基于 Elasticsearch 的全文关键词匹配。
      - match_phrase: sectionPath^8, chunkText^5, documentName^4
      - multi_match (BestFields): sectionPath^6, documentName^4, knowledgeScopeName^3, chunkText
      - 可选 filter 子句：文档路由、章节路径、结构化导航
      - 最低 should 匹配: minimum_should_match=1
    """

    @staticmethod
    def _build_es_query(query_text: str, sub_q: SubQuestion, limit: int) -> dict:
        should_clauses = [
            {"match_phrase": {"sectionPath": {"query": query_text, "boost": 8.0}}},
            {"match_phrase": {"chunkText": {"query": query_text, "boost": 5.0}}},
            {"match_phrase": {"documentName": {"query": query_text, "boost": 4.0}}},
            {
                "multi_match": {
                    "query": query_text,
                    "fields": [
                        "sectionPath^6",
                        "documentName^4",
                        "knowledgeScopeName^3",
                        "chunkText",
                    ],
                    "type": "best_fields",
                    "minimum_should_match": "1<50%",
                }
            },
        ]

        # 针对改写提取的关键词单独注入 should 加权匹配，避免污染主查询语法
        if getattr(sub_q, "query_context_hints", None):
            for kw in sub_q.query_context_hints[:5]:
                if kw and kw != query_text:
                    should_clauses.append({"match": {"chunkText": {"query": kw, "boost": 2.0}}})

        # 过滤条件值类型混杂（str / int / list），显式标注避免被首个子句收敛成 str
        filter_clauses: list[dict[str, Any]] = []
        # 租户过滤必须 fail-closed：缺失/空白时收敛到 default，避免跨租户检索。
        filter_clauses.append(
            {"term": {"tenantId": (sub_q.tenant_id or "").strip() or "default"}}
        )
        if sub_q.doc_ids:
            filter_clauses.append(
                {
                    "terms": {
                        "documentId": [d for d in (safe_int(x) for x in sub_q.doc_ids) if d != 0]
                    }
                }
            )
        if sub_q.structure_node_id is not None:
            filter_clauses.append({"term": {"structureNodeId": sub_q.structure_node_id}})
        if sub_q.section_path:
            filter_clauses.append({"match_phrase": {"sectionPath": sub_q.section_path}})
        if sub_q.canonical_path:
            filter_clauses.append({"prefix": {"canonicalPath": sub_q.canonical_path}})
        if sub_q.item_index is not None:
            filter_clauses.append({"term": {"itemIndex": sub_q.item_index}})
        if sub_q.document_name_hints:
            name_should = []
            for hint in sub_q.document_name_hints:
                name_should.append({"match_phrase": {"documentName": hint}})
            filter_clauses.append({"bool": {"should": name_should, "minimum_should_match": 1}})
        if sub_q.business_category_hints:
            filter_clauses.append({"terms": {"businessCategory": sub_q.business_category_hints}})
        if sub_q.document_tag_hints:
            filter_clauses.append({"terms": {"documentTags": sub_q.document_tag_hints}})

        return {
            "query": {
                "bool": {
                    "filter": filter_clauses,
                    "should": should_clauses,
                    "minimum_should_match": 1,
                }
            },
            "size": limit,
        }

    async def retrieve(self, sub_q: SubQuestion) -> list[Evidence]:
        if not sub_q.text or not sub_q.text.strip():
            return []

        query_text = (getattr(sub_q, "retrieval_query", None) or sub_q.text or "").strip()
        query_text = normalize_step_numeral(query_text)
        logger.debug("keyword channel query", query=query_text[:50])

        es = get_es()
        top_k = settings.rag.keyword_top_k
        max_k = getattr(settings.rag, "max_channel_top_k", 50) or 50
        limit = 10 if top_k <= 0 else min(top_k, max_k)

        query_body = self._build_es_query(query_text, sub_q, limit)

        try:
            res = await es.search(index=CHUNK_INDEX, body=query_body)
            hits = res.get("hits", {}).get("hits", [])

            if not hits:
                return await self._fallback_pgvector(query_text, sub_q, limit)

            evidences: list[Evidence] = []
            for hit in hits:
                score = hit["_score"] or 0.0
                source = hit.get("_source", {})
                section_path = source.get("sectionPath") or ""
                document_name = source.get("documentName") or ""
                evidences.append(
                    Evidence(
                        chunk_id=source.get("chunkId", ""),
                        content=source.get("chunkText", ""),
                        title=section_path or document_name or "未知文档片段",
                        source_type="document",
                        score=score,
                        original_score=score,
                        channel="keyword",
                        doc_id=str(source.get("documentId", "")),
                        document_name=document_name,
                        section_path=section_path,
                        section_title=leaf_section_title(section_path),
                    )
                )

            return evidences

        except Exception as e:
            logger.error(
                "elasticsearch query failed, falling back to pgvector", error=str(e), exc_info=True
            )
            return await self._fallback_pgvector(query_text, sub_q, limit)

    @staticmethod
    def _build_fallback_sql(terms: list[str], sub_q: SubQuestion, limit: int) -> tuple[str, list]:
        sql = "SELECT id as chunk_id, document_id, section_path, chunk_text, metadata_json->>'documentName' AS document_name, ("
        score_parts = []
        # args 混装 str / int / list，显式标注为 list[Any]
        args: list[Any] = []
        idx = 1
        for i, term in enumerate(terms):
            weight = max(1.0, 6.0 - i)
            score_parts.append(
                f"((CASE WHEN chunk_text LIKE ${idx} THEN 1.0 ELSE 0.0 END) + "
                f"(CASE WHEN section_path LIKE ${idx} THEN 1.5 ELSE 0.0 END)) * {weight}"
            )
            args.append(f"%{term}%")
            idx += 1

        sql += (
            " + ".join(score_parts)
            + ") AS similarity FROM pipeline_rag_document_embedding WHERE 1=1"
        )

        # 与 ES 主路径一致：租户 fail-closed 到 default。
        sql += f" AND tenant_id = ${idx}"
        args.append((sub_q.tenant_id or "").strip() or "default")
        idx += 1
        if sub_q.scope_code:
            sql += f" AND metadata_json->>'scope_code' = ${idx}"
            args.append(sub_q.scope_code)
            idx += 1
        if sub_q.doc_ids:
            doc_id_ints = [d for d in (safe_int(x) for x in sub_q.doc_ids) if d != 0]
            if doc_id_ints:
                sql += f" AND document_id = ANY(${idx}::bigint[])"
                args.append(doc_id_ints)
                idx += 1
        if sub_q.structure_node_id is not None:
            sql += f" AND structure_node_id = ${idx}"
            args.append(sub_q.structure_node_id)
            idx += 1
        if sub_q.section_path:
            sql += f" AND section_path LIKE ${idx}"
            args.append(sub_q.section_path + "%")
            idx += 1
        if sub_q.canonical_path:
            sql += f" AND canonical_path LIKE ${idx}"
            args.append(sub_q.canonical_path + "%")
            idx += 1
        if sub_q.item_index is not None:
            sql += f" AND item_index = ${idx}"
            args.append(sub_q.item_index)
            idx += 1
        if sub_q.business_category_hints:
            placeholders = ", ".join(
                f"${idx + i}" for i in range(len(sub_q.business_category_hints))
            )
            sql += f" AND metadata_json->>'businessCategory' = ANY(ARRAY[{placeholders}])"
            args.extend(sub_q.business_category_hints)
            idx += len(sub_q.business_category_hints)

        sql += f" AND (chunk_text LIKE ${1} "
        for i in range(2, len(terms) + 1):
            sql += f" OR chunk_text LIKE ${i} OR section_path LIKE ${i}"
        sql += ") "

        sql += f" ORDER BY similarity DESC LIMIT ${idx}"
        args.append(limit)

        return sql, args

    async def _fallback_pgvector(
        self, query_text: str, sub_q: SubQuestion, limit: int
    ) -> list[Evidence]:
        """PGVector SQL 回退方案 — Elasticsearch 不可用时降级为 PGVector 关键词模糊匹配"""
        from app.infra.pg import fetch as _pg_fetch
        from app.rag.keyword_extractor import extract_keyword_terms

        keyword_str = extract_keyword_terms(query_text)
        if not keyword_str:
            return []

        terms = keyword_str.split()
        if not terms:
            return []

        sql, args = self._build_fallback_sql(terms, sub_q, limit)

        evidences: list[Evidence] = []
        try:
            rows = await _pg_fetch(sql, *args)
        except Exception as e:
            logger.error("pgvector keyword fallback failed", error=str(e))
            return evidences

        for row in rows:
            if float(row["similarity"]) > 0:
                section_path = row["section_path"] or ""
                document_name = row.get("document_name") or ""
                evidences.append(
                    Evidence(
                        chunk_id=str(row["chunk_id"]),
                        content=row["chunk_text"],
                        title=section_path or document_name or "未知文档片段",
                        source_type="document",
                        score=float(row["similarity"]),
                        original_score=float(row["similarity"]),
                        channel="keyword",
                        doc_id=str(row["document_id"]),
                        document_name=document_name,
                        section_path=section_path,
                        section_title=leaf_section_title(section_path),
                    )
                )

        return evidences
