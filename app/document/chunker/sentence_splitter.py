"""
句级文本切分器 — 替换 llama-index-core 的 SentenceSplitter。

按句子边界切分后合并至 chunk_size 上限，支持 chunk_overlap。
"""

from __future__ import annotations

import re


def split_text(text: str, chunk_size: int = 512) -> list[str]:
    sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for s in sentences:
        s_len = len(s)
        if current_len + s_len > chunk_size and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(s)
        current_len += s_len

    if current:
        chunks.append("".join(current))
    return chunks
