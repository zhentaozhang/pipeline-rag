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


def make_chunk_id(doc_id: str, content: str, seq: int = 0, role: str = "child") -> str:
    """生成 Chunk 的 chunk_id。

    - 默认（``chunk.stable_chunk_id_enabled=false``）→ Snowflake：全局唯一、时间有序，
      与历史行为逐字节一致；
    - 开启 → **内容派生稳定 ID**：同一 ``(doc_id, role, seq, content)`` 在任意次重索引后
      得到相同的 ID，便于块级评估与版本 diff。``role`` 参与哈希，避免"父块与子块内容相同"
      （本语料 1:1 场景）时 ID 冲突。

    返回以字母开头（``c`` 前缀）的定长字符串，避免与纯数字 ID 混淆；下游
    ``stable_id_to_int`` 对其做确定性映射。
    """
    from app.config import get_settings

    if not getattr(get_settings().chunk, "stable_chunk_id_enabled", False):
        from app.infra.id_generator import next_id_str

        return next_id_str()

    import hashlib

    digest = hashlib.sha1(f"{doc_id}:{role}:{seq}:{content}".encode()).hexdigest()
    return "c" + digest[:24]
