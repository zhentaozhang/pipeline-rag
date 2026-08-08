"""session_service 纯函数测试：camelCase 递归转换、turn_status 解析（无 DB）。"""

from app.chat.session_service import _camel_case_keys, _parse_turn_status


class TestCamelCaseKeys:
    def test_flat_snake_to_camel(self):
        d = _camel_case_keys({"conversation_id": 1, "name": "x"})
        assert d == {"conversationId": 1, "name": "x"}

    def test_none_returns_none(self):
        assert _camel_case_keys(None) is None

    def test_empty_dict_unchanged(self):
        assert _camel_case_keys({}) == {}

    def test_recursive_nested_dicts(self):
        d = _camel_case_keys({"outer_key": {"inner_key": 1}})
        assert d == {"outerKey": {"innerKey": 1}}

    def test_recursive_lists_of_dicts(self):
        d = _camel_case_keys({"items": [{"item_id": 1}, {"item_id": 2}]})
        assert d == {"items": [{"itemId": 1}, {"itemId": 2}]}

    def test_mutates_in_place(self):
        original = {"a_b": 1}
        result = _camel_case_keys(original)
        assert result is original
        assert "aB" in original


class TestParseTurnStatus:
    def test_digit_string_returns_int(self):
        assert _parse_turn_status("3") == 3

    def test_all_returns_none(self):
        assert _parse_turn_status("ALL") is None
        assert _parse_turn_status("all") is None

    def test_empty_and_none_return_none(self):
        assert _parse_turn_status(None) is None
        assert _parse_turn_status("") is None

    def test_enum_name_returns_value(self):
        assert _parse_turn_status("COMPLETED") == 2
        assert _parse_turn_status("FAILED") == 3
        assert _parse_turn_status("STOPPED") == 4

    def test_enum_name_case_insensitive(self):
        assert _parse_turn_status("completed") == 2

    def test_invalid_string_returns_none(self):
        assert _parse_turn_status("not-a-status") is None
