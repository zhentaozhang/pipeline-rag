"""索引时把编号类 token 写进派生 keyword 字段（供 term 查询精确定位）。"""

from app.document.indexer import enrich_chunk_document


def test_enrich_chunk_document_fills_derived_fields():
    doc = {
        "chunkId": "c1",
        "documentName": "华远科技集团差旅与报销管理制度",
        "sectionPath": "第9条 住宿费用限额",
        "chunkText": "**9.1** 总监级（M4+）800元/晚 A类城市",
    }
    out = enrich_chunk_document(doc)
    assert out["clauseNumber"] == ["9"]
    assert out["subClauseNumbers"] == ["9.1"]
    assert out["docNameKeyword"] == "华远科技集团差旅与报销管理制度"
    assert "M4+" in out["gradeCodes"]
    assert out["cityClasses"] == ["A"]


def test_enrich_chunk_document_tolerates_missing_fields():
    out = enrich_chunk_document({"chunkId": "c2", "chunkText": "普通正文"})
    assert out["clauseNumber"] == []
    assert out["subClauseNumbers"] == []
    assert out["docNameKeyword"] == ""
    assert out["gradeCodes"] == []
    assert out["cityClasses"] == []


def test_enrich_chunk_document_keeps_original_keys():
    doc = {
        "chunkId": "c3",
        "sectionPath": "第5条 试用期",
        "chunkText": "试用期最长不超过六个月",
        "tenantId": "default",
    }
    out = enrich_chunk_document(doc)
    assert out["chunkId"] == "c3"
    assert out["tenantId"] == "default"
    assert out["clauseNumber"] == ["5"]
