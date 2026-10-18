"""候选生成逻辑的契约测试（生成器只产出候选，终审后手写进 lexical_dataset.py）。"""

from scripts.evaluation.generate_lexical_questions import build_candidates


def _row(chunk_id: str, doc: str, path: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_block_id": None,
        "document_name": doc,
        "section_path": path,
        "chunk_text": text,
    }


def test_ambiguous_clause_collects_all_documents() -> None:
    rows = [
        _row("1", "A制度.md", "第9条 住宿费用限额", "**9.1** 上限 800元/晚"),
        _row("2", "B制度.md", "第9条 加班管理", "加班按 1.5 倍计"),
    ]
    cands = build_candidates(rows)
    amb = [c for c in cands if c["subtype"] == "clause_ambiguous"]
    assert len(amb) == 1
    assert amb[0]["clause"] == "9"
    assert amb[0]["gold_chunk_ids"] == ["1", "2"]


def test_subclause_and_grade_candidates() -> None:
    rows = [
        _row("1", "差旅.md", "第9条 住宿费用限额", "**9.1** 总监级（M4+） 800元/晚 A类城市"),
    ]
    cands = build_candidates(rows)
    subtypes = {c["subtype"] for c in cands}
    assert {"clause_doc", "clause_sub", "clause_grade"} <= subtypes
    sub = next(c for c in cands if c["subtype"] == "clause_sub")
    assert sub["subclause"] == "9.1"
    grade = next(c for c in cands if c["subtype"] == "clause_grade")
    assert grade["gold_chunk_ids"] == ["1"]


def test_rows_without_clause_are_ignored() -> None:
    assert build_candidates([_row("1", "A.md", "前言", "无关内容")]) == []
