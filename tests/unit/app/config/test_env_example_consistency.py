"""`.env.example` 必须与代码默认值一致。

模板漂移会让"没写 .env 的部署"和"照抄 .env.example 的部署"跑出两套行为
（本轮就发现 RANK1_GUARD / MIN_VECTOR_SIMILARITY / MULTI_HOP_SPLIT 三处反向漂移）。
"""

from __future__ import annotations

from pathlib import Path

from app.config.pipeline import RAGSettings

_ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"

# 只钉住"检索主链路"的旋钮：改这些等于改线上召回行为，必须模板与代码同源
_RETRIEVAL_KEYS = (
    "RAG_VECTOR_TOP_K",
    "RAG_KEYWORD_TOP_K",
    "RAG_CANDIDATE_TOP_K",
    "RAG_FINAL_TOP_K",
    "RAG_KEYWORD_MINIMUM_SHOULD_MATCH",
    "RAG_RRF_K",
    "RAG_RRF_VECTOR_WEIGHT",
    "RAG_RRF_KEYWORD_WEIGHT",
    "RAG_VECTOR_RELATIVE_RATIO",
    "RAG_MIN_VECTOR_SIMILARITY",
    "RAG_RERANK_MIN_SCORE",
    "RAG_RERANK_RELATIVE_RATIO",
    "RAG_RERANK_RANK1_GUARD_ENABLED",
    "RAG_RERANK_FILTER_STARVATION_GUARD_ENABLED",
    "RAG_MULTI_HOP_SPLIT_ENABLED",
    "RAG_REFERENCE_SNIPPET_MAX_CHARS",
    "RAG_PARENT_EVIDENCE_MAX_CHARS",
    "RAG_PROMPT_BUDGET_PER_SUBQUESTION",
    "RAG_PROMPT_BUDGET_TOTAL",
    "RAG_EVALUATION_ENABLED",
)


def _parse_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # 行内注释：`KEY=0  # 说明`
        value = value.split("#", 1)[0].strip()
        values[key.strip()] = value
    return values


def _coerce(field_type: str, raw: str):
    if field_type is bool or field_type == "bool":
        return raw.lower() in {"1", "true", "yes", "on"}
    if field_type is int or field_type == "int":
        return int(raw)
    if field_type is float or field_type == "float":
        return float(raw)
    return raw


def test_retrieval_keys_in_example_match_code_defaults():
    env = _parse_env_example()
    # _env_file=None：要比较的是"代码默认值"，不能被本机 .env 覆盖
    defaults = RAGSettings(_env_file=None)
    mismatches = []
    for key in _RETRIEVAL_KEYS:
        assert key in env, f"{key} 未出现在 .env.example"
        field_name = key[len("RAG_") :].lower()
        expected = getattr(defaults, field_name)
        actual = _coerce(type(expected).__name__, env[key])
        if actual != expected:
            mismatches.append((key, env[key], expected))
    assert not mismatches, f"模板与代码默认值漂移: {mismatches}"


def test_bool_keys_use_lowercase_true_false():
    env = _parse_env_example()
    bad = [
        (k, v)
        for k, v in env.items()
        if v in {"True", "False", "TRUE", "FALSE"} and k.startswith(("RAG_", "RERANK_"))
    ]
    assert not bad, f"布尔值应写成小写 true/false: {bad}"
