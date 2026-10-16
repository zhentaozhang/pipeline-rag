def count_tokens(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        return len(text)


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    """截断文本以确保不超过 max_tokens（字符与 Token 双重安全防护）"""
    if not text or max_tokens <= 0:
        return text
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    except (ImportError, Exception):
        char_limit = max_tokens * 2
        return text[:char_limit] if len(text) > char_limit else text
