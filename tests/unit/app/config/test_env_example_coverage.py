"""第三轮优化 #3：.env.example 配置漂移校验

新加配置必须同步进 .env.example，否则用户无法发现/启用。
本测试锁定关键分组配置，防止未来再漂移。
"""

from pathlib import Path

_ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"

# (配置组, 期望出现的 key 前缀)
_REQUIRED_GROUPS = {
    "查询自适应 Top-k（P2）": ["RAG_ADAPTIVE_K_ENABLED", "RAG_ADAPTIVE_K_MIN_K", "RAG_ADAPTIVE_K_MAX_K", "RAG_ADAPTIVE_K_RATIO_THRESHOLD"],
    "用户事实记忆（P3）": ["RAG_USER_MEMORY_ENABLED", "RAG_USER_MEMORY_RETRIEVAL_TOP_K", "RAG_USER_MEMORY_UPDATE_THRESHOLD", "RAG_USER_MEMORY_MAX_FACTS", "RAG_USER_MEMORY_RETENTION_DAYS"],
    "Prompt Caching（P0）": ["LLM_CACHE_HIT_PRICE_FACTOR"],
    "对话响应缓存（006）": ["CHAT_CACHE_ENABLED", "CHAT_CACHE_TTL_HOURS"],
    "飞书渠道（P3-4）": ["FEISHU_ENABLED", "FEISHU_APP_ID", "FEISHU_APP_SECRET"],
    "S3 连接器（P3-3）": ["CONNECTOR_S3_ENABLED", "CONNECTOR_S3_BUCKET"],
    "网页爬虫连接器（P3-3）": ["CONNECTOR_WEB_ENABLED"],
    "MinerU（P2-4）": ["MINERU_ENABLED"],
}


def test_env_example_covers_recent_config_groups():
    assert _ENV_EXAMPLE.exists(), f"{_ENV_EXAMPLE} not found"
    content = _ENV_EXAMPLE.read_text(encoding="utf-8")

    missing: list[str] = []
    for group, keys in _REQUIRED_GROUPS.items():
        for key in keys:
            if f"{key}=" not in content:
                missing.append(f"{group}: {key}")

    assert not missing, (
        "以下配置未同步到 .env.example（用户无法发现/启用），请补全：\n" + "\n".join(missing)
    )
