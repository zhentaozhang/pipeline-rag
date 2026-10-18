"""P2-6 查询类型自适应融合权重：分类器纯逻辑测试（无网络）。"""

from app.rag.engine import _query_type_multipliers


class TestQueryTypeMultipliers:
    def test_numeric_query_prefers_keyword(self):
        assert _query_type_multipliers("住宿标准 450 元", 1.6, 1.6) == (1.0, 1.6)

    def test_clause_reference_prefers_keyword(self):
        assert _query_type_multipliers("第3条关于请假的规定", 1.6, 1.6) == (1.0, 1.6)

    def test_version_or_license_prefers_keyword(self):
        assert _query_type_multipliers("GPL 许可证能否引入", 1.6, 1.6) == (1.0, 1.6)

    def test_concept_query_prefers_vector(self):
        assert _query_type_multipliers("如何理解公司的企业文化", 1.6, 1.6) == (1.6, 1.0)

    def test_custom_biases_respected(self):
        assert _query_type_multipliers("住宿标准 450 元", 2.0, 0.5) == (1.0, 2.0)
        assert _query_type_multipliers("如何理解企业文化", 2.0, 0.5) == (0.5, 1.0)
