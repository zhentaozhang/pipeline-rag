"""编号类 token 抽取（条款号 / 子条款号 / 文档名 / 职级 / 城市类别）。"""

from app.rag.query_tokens import cn_to_int, derive_chunk_tokens, extract_query_tokens


def test_cn_to_int_basic():
    assert cn_to_int("九") == 9
    assert cn_to_int("十") == 10
    assert cn_to_int("十二") == 12
    assert cn_to_int("二十") == 20
    assert cn_to_int("二十三") == 23
    assert cn_to_int("99") == 99
    assert cn_to_int("条") is None


def test_extract_clause_arabic_and_chinese():
    assert extract_query_tokens("第9条规定了什么").clauses == ["9"]
    assert extract_query_tokens("第 9 条").clauses == ["9"]
    assert extract_query_tokens("第九条").clauses == ["9"]
    assert extract_query_tokens("第十二条").clauses == ["12"]


def test_extract_subclause_and_doc_name():
    tokens = extract_query_tokens("《华远科技集团差旅与报销管理制度》9.1 的内容")
    assert tokens.subclauses == ["9.1"]
    assert tokens.doc_names == ["华远科技集团差旅与报销管理制度"]


def test_extract_grade_and_city_class():
    tokens = extract_query_tokens("经理级 M3 在 B 类城市的住宿上限")
    assert tokens.grades == ["M3"]
    assert tokens.city_classes == ["B"]


def test_derive_chunk_tokens_from_path_and_text():
    out = derive_chunk_tokens(
        "第9条 住宿费用限额",
        "**9.1** 每日上限 总监级（M4+） 800元/晚 A类城市",
    )
    assert out["clauseNumber"] == ["9"]
    assert out["subClauseNumbers"] == ["9.1"]
    assert "M4+" in out["gradeCodes"]
