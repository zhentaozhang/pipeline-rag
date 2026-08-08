from app.rag.keyword_extractor import (
    CHINESE_NOISE_PHRASES,
    _add_character_ngrams,
    _add_sliding_ngrams,
    extract_keyword_terms,
)


class TestExtractKeywordTerms:
    def test_empty(self):
        assert extract_keyword_terms("") == ""
        assert extract_keyword_terms(None) == ""

    def test_noise_words_removed(self):
        result = extract_keyword_terms("请问如何配置数据库连接")
        assert "请问" not in result
        assert "如何" not in result
        assert "配置" in result
        assert "数据库" in result
        assert "连接" in result

    def test_noise_only_input(self):
        assert extract_keyword_terms("请问") == ""
        assert extract_keyword_terms("帮我总结一下") == ""

    def test_connective_split(self):
        result = extract_keyword_terms("数据库和缓存及队列")
        assert "数据库" in result
        assert "缓存" in result
        assert "队列" in result

    def test_alnum_token_kept_whole(self):
        result = extract_keyword_terms("查询订单号 ORD-20240101 的状态")
        assert "ORD-20240101" in result

    def test_max_terms_limit(self):
        result = extract_keyword_terms("数据库连接池配置与优化")
        assert len(result.split(" ")) <= 8

    def test_returns_space_joined(self):
        result = extract_keyword_terms("数据库连接池配置")
        assert isinstance(result, str)
        assert " " in result


class TestAddSlidingNgrams:
    def test_bigram_chinese_concatenated(self):
        assert "数据库连接" in _add_sliding_ngrams(["数据库", "连接"])

    def test_trigram(self):
        ngrams = _add_sliding_ngrams(["向量", "检索", "系统"])
        assert "向量检索" in ngrams
        assert "检索系统" in ngrams
        assert "向量检索系统" in ngrams

    def test_english_joined_with_space(self):
        assert _add_sliding_ngrams(["apple", "banana"]) == ["apple banana"]

    def test_single_token_no_ngrams(self):
        assert _add_sliding_ngrams(["配置"]) == []

    def test_mixed_chinese_english(self):
        ngrams = _add_sliding_ngrams(["deep", "学习"])
        assert "deep 学习" in ngrams


class TestAddCharacterNgrams:
    def test_short_token(self):
        assert _add_character_ngrams("a") == []
        assert _add_character_ngrams("ab") == ["ab", "ab"]

    def test_prefix_and_suffix(self):
        ngrams = _add_character_ngrams("数据")
        assert "数" not in ngrams
        assert "数据" in ngrams

    def test_sliding_inner_substrings(self):
        ngrams = _add_character_ngrams("abcdef")
        assert "bc" in ngrams
        assert "bcd" in ngrams
        assert "bcde" in ngrams
        assert "cde" in ngrams

    def test_max_length_four(self):
        ngrams = _add_character_ngrams("abcdef")
        assert all(len(g) <= 4 for g in ngrams)
        assert "abcde" not in ngrams

    def test_full_token_excluded(self):
        ngrams = _add_character_ngrams("abc")
        assert "abc" in ngrams  # prefix 含完整词
        ngrams6 = _add_character_ngrams("abcdef")
        assert "abcdef" not in ngrams6  # 滑动子串不含完整词


class TestNoisePhrases:
    def test_common_phrases_present(self):
        for phrase in ["请问", "帮我", "给我", "如何", "是什么", "为什么", "的"]:
            assert phrase in CHINESE_NOISE_PHRASES
