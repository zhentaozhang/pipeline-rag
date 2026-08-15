"""
关键词提取器
负责对 Query 进行：
1. 中文分词 (jieba)
2. 停用词/噪声词过滤 (CHINESE_NOISE_PHRASES)
3. n-gram (Bi-gram, Tri-gram) 生成，提升关键词检索的连续命中率
"""

import re

import jieba

CHINESE_NOISE_PHRASES = {
    "请问",
    "帮我",
    "给我",
    "详细",
    "介绍",
    "一下",
    "分析",
    "总结",
    "是什么",
    "为什么",
    "怎么",
    "如何",
    "在哪里",
    "什么时候",
    "的",
}


def _add_sliding_ngrams(tokens: list[str]) -> list[str]:
    """生成滑动 n-grams (Bi-grams, Tri-grams)"""
    ngrams = []
    n = len(tokens)
    if n >= 2:
        for i in range(n - 1):
            if re.search(r"[a-zA-Z]", tokens[i]) or re.search(r"[a-zA-Z]", tokens[i + 1]):
                ngrams.append(" ".join([tokens[i], tokens[i + 1]]))
            else:
                ngrams.append(tokens[i] + tokens[i + 1])
    if n >= 3:
        for i in range(n - 2):
            if (
                re.search(r"[a-zA-Z]", tokens[i])
                or re.search(r"[a-zA-Z]", tokens[i + 1])
                or re.search(r"[a-zA-Z]", tokens[i + 2])
            ):
                ngrams.append(" ".join([tokens[i], tokens[i + 1], tokens[i + 2]]))
            else:
                ngrams.append(tokens[i] + tokens[i + 1] + tokens[i + 2])
    return ngrams


def _add_character_ngrams(token: str) -> list[str]:
    """字符级 head/tail/sliding n-grams（前缀/后缀/滑动，最大长度 4）"""
    ngrams: list[str] = []
    n = len(token)
    if n < 2:
        return ngrams

    max_len = min(4, n)
    # prefixes (head)
    for i in range(2, max_len + 1):
        ngrams.append(token[:i])

    # suffixes (tail)
    for i in range(2, max_len + 1):
        ngrams.append(token[-i:])

    # sliding substrings
    if n > 2:
        for i in range(1, n - 1):
            for length in range(2, max_len + 1):
                if i + length < n:  # exclude full token or prefix/suffix that were already caught
                    ngrams.append(token[i : i + length])

    return ngrams


def extract_keyword_terms(text: str) -> str:
    """
    提取查询文本的核心关键词，包含分词及 n-grams 增强。
    返回以空格分隔的词条串，用于 ES multi_match 的 query 字段。
    """
    if not text:
        return ""

    # 0. 连接词分割
    clean_text = text
    for conn in ["的", "和", "及", "与", "或"]:
        clean_text = clean_text.replace(conn, " ")

    # 1. 过滤噪声词
    for noise in CHINESE_NOISE_PHRASES:
        clean_text = clean_text.replace(noise, " ")

    # 2. 提取连续的英文数字词 (例如 UUID, 订单号等，保持完整)
    alnum_pattern = re.compile(r"[a-zA-Z0-9_\-]+")
    alnum_tokens = alnum_pattern.findall(clean_text)

    # 3. 中文分词
    cn_text = alnum_pattern.sub(" ", clean_text)
    raw_tokens = list(jieba.cut(cn_text))

    # 过滤空字符和单字
    cn_tokens = [t.strip() for t in raw_tokens if t.strip() and not re.match(r"^\W+$", t.strip())]

    # 4. 生成 token-level n-grams
    token_ngrams = _add_sliding_ngrams(cn_tokens)

    # 5. 生成 character-level n-grams
    char_ngrams = []
    for t in cn_tokens + alnum_tokens:
        char_ngrams.extend(_add_character_ngrams(t))

    # 6. 合并并去重
    final_terms_set = set(alnum_tokens + cn_tokens + token_ngrams + char_ngrams)

    # 7. MAX_KEYWORD_TERMS=8 限制 (优先保留原始分词中较长的)
    final_terms = list(final_terms_set)
    final_terms.sort(key=len, reverse=True)
    MAX_KEYWORD_TERMS = 8

    return " ".join(final_terms[:MAX_KEYWORD_TERMS])
