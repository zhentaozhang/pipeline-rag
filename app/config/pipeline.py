from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class CelerySettings(BaseSettings):
    """Celery 异步任务配置"""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"

    model_config = SettingsConfigDict(env_prefix="CELERY_", env_file=_ENV_FILE, extra="ignore")


class FactMemorySettings(BaseSettings):
    """用户事实记忆（调研 P3 · Mem0 式）：跨轮抽取用户事实/偏好，检索注入个性化回答"""

    enabled: bool = False  # 默认关（隐私安全）；开启后抽取/检索才生效
    extract_sample_rate: float = 1.0  # 抽取采样率（每轮是否触发异步抽取）
    retrieval_top_k: int = 3  # 注入 prompt 的相关记忆条数
    retrieval_distance_threshold: float = (
        0.70  # 余弦距离阈值（<=此值视为相关；余弦距离 = 1 - cosine_similarity）
    )
    update_threshold: float = 0.92  # 相似度高于此值视为已有事实（去重）
    max_facts: int = 200  # 单会话事实条数上限（超出按最旧淘汰）
    retention_days: int = 180  # 全局保留期（edit_time 早于此删除；0=不限）

    model_config = SettingsConfigDict(
        env_prefix="RAG_USER_MEMORY_", env_file=_ENV_FILE, extra="ignore"
    )


class AdaptiveKSettings(BaseSettings):
    """查询自适应 Top-k 截断（调研 P2）：RRF 前按得分分布动态截断，默认关闭"""

    enabled: bool = False
    min_k: int = 3  # 保底召回下限
    max_k: int = 20  # 单通道候选上限（成本控制）
    ratio_threshold: float = 0.4  # 得分低于最高分×ratio 且已超 min_k 即截断

    model_config = SettingsConfigDict(
        env_prefix="RAG_ADAPTIVE_K_", env_file=_ENV_FILE, extra="ignore"
    )


class RAGSettings(BaseSettings):
    """RAG 检索参数"""

    enabled: bool = True
    # 默认值与 .env.example 对齐（宽召回：单通道 50 → 融合 50 → 最终 8）。
    # 避免"未提供 .env 的部署/CI"回落到过窄的候选池（原 5/5/6/5）。
    vector_top_k: int = 50
    keyword_top_k: int = 50
    candidate_top_k: int = 50
    final_top_k: int = 8
    min_vector_similarity: float = 0.55
    keyword_score_ratio: float = 0.35
    # RRF 融合参数（P1）：k 越小越强调单路排名靠前的候选；权重控制双通道相对影响力。
    # 企业规章切块精准场景下推荐 k=30，更能凸显单通道 Top-1 优势。
    rrf_k: int = 30
    rrf_vector_weight: float = 1.0
    rrf_keyword_weight: float = 1.0
    # P2-6 查询类型自适应融合：精确标识型查询偏关键词、概念型偏向量（默认关）。
    query_adaptive_weight_enabled: bool = False
    adaptive_keyword_bias: float = 1.6
    adaptive_vector_bias: float = 1.6
    context_window_safety_margin: float = 0.15
    prompt_budget_total: int = 5200
    prompt_budget_per_subquestion: int = 2200
    parent_evidence_max_chars: int = 2200
    # 单条引用渲染上限（P1）：此前硬编码 1100，导致父块预算(2200/4000)在实际 Prompt 中失效。
    reference_snippet_max_chars: int = 2000
    # 评测裁判可见上下文上限（与生成侧预算对齐，避免"裁判看到的证据 < 模型看到的证据"）。
    eval_context_max_chars: int = 20000
    # 召回归因覆盖判定阈值（诊断用，可配）。
    stage_attribution_cover_ratio: float = 0.35
    # 向量通道门限：默认绝对阈值；>0 时改用相对阈值 top_score*ratio（生产由 .env 开启 0.35）。
    vector_relative_ratio: float = 0.0
    vector_near_miss_ratio: float = 0.85
    # R1 条件重排：第一阶段 top-1 相似度 >= 该值时跳过重排（0=关闭）。
    rerank_skip_min_similarity: float = 0.0
    # R2 rank-1 保护：重排后若第一阶段首候选被降级、但其重排分与新榜首差距 <= margin，则恢复其榜首。
    rerank_rank1_guard_enabled: bool = True
    rerank_rank1_guard_margin: float = 0.15
    # D3 不变量（默认开）：重排阈值若把证据集砍到 final_top_k 以下，自动跳过阈值并告警。
    # 防止"阈值误配 → 上下文饥饿 → 召回坍塌"（实测曾导致 R@10 0.837→0.733）。
    rerank_filter_starvation_guard_enabled: bool = True
    # 单通道抓取安全上限（解除写死 50 限制）
    max_channel_top_k: int = 100
    # 通道开关：关闭向量通道可做"纯关键词"离线验证（零外部调用）。
    vector_channel_enabled: bool = True
    planning_history_max_chars: int = 1600
    answer_history_max_chars: int = 1000
    # 更深候选池(50)+更宽重排(top_n=10)下放宽通道/子问题超时，避免静默降级。
    channel_timeout_ms: int = 8000
    sub_question_timeout_ms: int = 20000
    keyword_channel_enabled: bool = True
    # P1-3 元数据预过滤：把问题里提取到的"章节提示"（如"第8条/附录A"）经**存在性校验**后
    # 落为 section_path 前缀过滤（双通道同时收窄）。校验失败即跳过，绝不因过滤制造零召回。
    # 默认关；开启后仅对"确实引用了语料中存在的章节"的查询生效。
    metadata_prefilter_enabled: bool = False
    metadata_prefilter_cache_ttl_seconds: float = 300.0
    # P2-7 LongContextReorder（默认关）：把证据重排为"首尾最相关、中部最不相关"，
    # 缓解 lost-in-the-middle。仅改渲染顺序、不改内容；仅在整组证据能放进预算时生效，
    # 以免截断优先丢弃尾部（尾部是次相关项）。
    long_context_reorder_enabled: bool = False
    # P3-8 迭代式多跳（默认关，需 LLM）：检索→用已获证据生成"下一跳查询"→再检索，累积去重。
    # 由"下一跳查询为空/重复"自然收敛；任一环节异常即停止，不打断检索主链路。
    iterative_multi_hop_enabled: bool = False
    iterative_multi_hop_max_hops: int = 2
    max_sub_questions: int = 4
    # P2 多跳拆分：复合/多条件（含 且/并且/同时/满足…等条件连接）单句问题拆为多个检索子查询。
    # A/B 实测（25 题）：R@10 持平、R@5/命中略降，未验证收益，故默认关（opt-in）。
    # 用 runner --multi-hop-split 开启做对照；待 chunk/embedding 优化后复测再评估是否转正。
    multi_hop_split_enabled: bool = True
    no_evidence_reply: str = "当前没有从已接入文档中检索到足够证据，暂时不能给出可靠结论。"
    stream_timeout_seconds: int = 600
    answer_system_prompt: str = ""
    answer_max_chars: int = 0  # 回答长度上限（0=不限；>0 时 prompt 注入简明约束，D 项 A/B）
    citation_verify_enabled: bool = (
        True  # 017 生成侧：引用验证器（每轮 1 次轻量 LLM 自检引用-证据对应）
    )
    citation_verify_parallel_enabled: bool = (
        True  # P1-c：引用校验与质量自审并发预跑（False 回退串行）
    )
    route_candidate_embed_cache_enabled: bool = True  # P2：路由候选 route_text 嵌入内容哈希缓存
    rewrite_enabled: bool = True
    rewrite_history_turns: int = 4
    rewrite_temperature: float = 0.1
    rewrite_top_p: float = 0.3
    rewrite_thinking: bool = False
    # 在线评估：生成后对成功回答做 LLM 打分（Faithfulness/Relevancy/ContextPrecision…）。
    # 默认关：每轮额外 3~5 次 LLM 调用，成本敏感场景不背锅。
    # 启用必须同时满足 evaluation_enabled=true 且 evaluation_sample_rate>0；
    # 离线评估走 Langfuse dataset/experiment，不依赖此开关。
    evaluation_enabled: bool = False
    evaluation_model: str = ""
    evaluation_base_url: str = ""
    evaluation_api_key: str = ""
    evaluation_timeout_seconds: int = 30
    evaluation_sample_rate: float = 0.0
    evidence_min_score: float = 0.1
    rerank_min_score: float = 0.35  # 绝对下限：滤无关块（0.10-0.25）不伤相关块（0.45+）
    # P1 相对阈值：保留 rerank_score >= top_score * ratio 的候选（默认 0.35 相对放行）。
    # 避免"整体低分区间被一刀切"造成的召回坍塌（如 0.17/0.06 全被 0.35 滤掉）。
    rerank_relative_ratio: float = 0.35
    knowledge_route_confidence_threshold: float = 0.40
    vectorize_batch_size: int = 10
    # P0-2: Contextual Chunking——embedding 文本附加文档名+章节路径（重索引后生效，可回退关闭）
    contextual_chunking_enabled: bool = True
    # P0-1 真 Contextual Retrieval（Anthropic 方法，默认关，需重索引才生效、可回退）：
    # 用 LLM 为每个子块生成 50~100 token 的"文档内上下文"，前置进 embedding 文本。
    # 任一环节失败自动回退到上面的"文档名+章节路径"版本，绝不阻断入库。
    contextual_llm_enabled: bool = False
    contextual_llm_model: str = ""  # 空 = 用 settings.llm.model
    contextual_llm_max_doc_chars: int = 24000  # 作为生成参考的文档正文上限
    contextual_max_tokens: int = 120  # 生成上下文的输出上限
    contextual_llm_concurrency: int = 4
    supervisor_enabled: bool = True
    # P0-1c: LLM 分解前规则预筛——仅复合/分析类/长问题触发分解，简单问题零 LLM 成本
    supervisor_rule_prefilter: bool = True
    supervisor_temperature: float = 0.1
    supervisor_max_review_retries: int = 2
    quality_enabled: bool = True
    quality_max_retries: int = 2
    quality_min_score: float = 7.0
    quality_model: str = ""
    quality_check_timeout_seconds: float = 5.0
    corrective_retrieval_enabled: bool = True
    corrective_retrieval_max_rounds: int = 1
    sub_question_max_concurrency: int = 3

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=_ENV_FILE, extra="ignore")


class AgentSettings(BaseSettings):
    """Agent 安全限制 + 系统提示词"""

    max_model_calls_per_run: int = 8
    max_tool_calls_per_run: int = 6
    max_model_calls_per_session: int = 40
    max_tool_calls_per_session: int = 30
    system_prompt: str = ""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=_ENV_FILE, extra="ignore")


class MemorySettings(BaseSettings):
    """会话记忆配置"""

    enabled: bool = True
    strategy: Literal["none", "sliding_window", "summary_compression"] = "summary_compression"
    window_size: int = 4
    max_summary_chars: int = 1400
    max_window_chars: int = 2200
    summary_batch_size: int = 6
    max_section_items: int = 6
    max_item_length: int = 80

    model_config = SettingsConfigDict(env_prefix="MEMORY_", env_file=_ENV_FILE, extra="ignore")


class ChunkSettings(BaseSettings):
    """文档分段参数"""

    recursive_max_chars: int = 800
    recursive_overlap_chars: int = 120
    semantic_max_chars: int = 700
    semantic_min_chars: int = 240
    semantic_similarity_threshold: float = 0.18
    llm_enabled: bool = False
    llm_max_chars: int = 3500
    recommend_llm_when_low_quality: bool = True
    # P0-2 粒度校准：结构解析按"每节点一块"产生大量小片段（实测受手册中位 ~99 token）。
    # 开启后把相邻小节点贪心合并到目标 token 窗口（研究推荐 256~512）。默认关，需重索引才生效。
    merge_small_sections_enabled: bool = False
    merge_target_tokens: int = 320
    merge_max_tokens: int = 512
    # P1-5 稳定 chunk ID（默认关）：开启后 chunk_id 由 (doc, role, seq, content) 内容派生，
    # 同一输入在任意次重索引后得到相同 ID，便于块级评估与版本 diff。默认 Snowflake（不变）。
    stable_chunk_id_enabled: bool = False

    model_config = SettingsConfigDict(env_prefix="CHUNK_", env_file=_ENV_FILE, extra="ignore")


class StructureParsingSettings(BaseSettings):
    """文档结构解析参数"""

    max_plain_heading_chars: int = 32
    llm_disambiguation_enabled: bool = True
    ambiguity_confidence_floor: float = 0.45
    ambiguity_confidence_ceil: float = 0.80
    max_ambiguous_signals_per_call: int = 8
    context_window_lines: int = 2

    model_config = SettingsConfigDict(env_prefix="STRUCTURE_", env_file=_ENV_FILE, extra="ignore")


class RecommendationSettings(BaseSettings):
    """推荐追问配置"""

    enabled: bool = False  # 017 决策：默认关（省 ~2s/轮，延迟敏感场景不背锅）；产品需要时 RECOMMEND_ENABLED=true 开启
    timeout_ms: int = 3000

    model_config = SettingsConfigDict(env_prefix="RECOMMEND_", env_file=_ENV_FILE, extra="ignore")


class ChatCacheSettings(BaseSettings):
    """对话响应缓存（第二轮架构评审·可以优化 3）：缓存无历史上下文的确定性问答"""

    enabled: bool = False
    ttl_hours: int = 24

    model_config = SettingsConfigDict(env_prefix="CHAT_CACHE_", env_file=_ENV_FILE, extra="ignore")


class FeishuSettings(BaseSettings):
    """飞书机器人渠道（P3-4）：长连接事件订阅 + 卡片流式回复"""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    stream_update_interval_ms: int = 500  # 卡片流式更新节流间隔（飞书更新接口有限频）
    bot_open_id: str = ""  # 可选：机器人 open_id（群聊 @ 精确判断，不配则 mentions 非空即响应）
    web_base_url: str = "http://localhost:5173"  # 平台 Web 地址（引用溯源跳转）

    model_config = SettingsConfigDict(env_prefix="FEISHU_", env_file=_ENV_FILE, extra="ignore")


class S3ConnectorSettings(BaseSettings):
    """S3 数据源连接器（P3-3）：扫描 S3 bucket 并导入文档处理流水线"""

    enabled: bool = False
    endpoint: str = "https://s3.amazonaws.com"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    prefix: str = ""  # 对象前缀过滤（如 "documents/rag/"）
    file_types: str = ".pdf,.docx,.doc,.txt,.md,.pptx,.xlsx"  # 逗号分隔扩展名
    batch_size: int = 10
    temp_dir: str = "/tmp/rag-connector-s3"

    model_config = SettingsConfigDict(
        env_prefix="CONNECTOR_S3_", env_file=_ENV_FILE, extra="ignore"
    )


class WebConnectorSettings(BaseSettings):
    """网页爬虫连接器（P3-3）：抓取公开站点内容导入文档流水线"""

    enabled: bool = False
    seed_urls: str = ""  # 逗号分隔种子页（无 sitemap 时从此递归发现）
    sitemap_url: str = ""  # sitemap.xml 地址（企业站标配，优先）
    max_pages: int = 50
    max_depth: int = 2  # 种子递归抓取深度
    concurrency: int = 4
    delay_seconds: float = 0.5  # 请求间隔，避免对目标站点造成压力
    respect_robots: bool = True
    user_agent: str = ""

    model_config = SettingsConfigDict(
        env_prefix="CONNECTOR_WEB_", env_file=_ENV_FILE, extra="ignore"
    )


class MinerUSettings(BaseSettings):
    """MinerU 文档解析增强通道（P2-4）：复杂版式（扫描件/表格/多栏）走 MinerU，失败降级 unstructured"""

    enabled: bool = False
    base_url: str = "https://mineru.net"
    api_key: str = ""
    mode: str = "agent"  # agent（免 token，≤10MB/20页）| extract（需 token，≤200MB/200页）
    timeout_seconds: int = 60
    poll_interval_seconds: int = 2
    max_poll_retries: int = 30

    model_config = SettingsConfigDict(env_prefix="MINERU_", env_file=_ENV_FILE, extra="ignore")


class RateLimitSettings(BaseSettings):
    """Redis 滑动窗口限流配置"""

    enabled: bool = True
    chat_calls: int = 10
    chat_window_seconds: int = 60
    auth_calls: int = 20
    auth_window_seconds: int = 60
    manage_calls: int = 60
    manage_window_seconds: int = 60
    # 信任的反向代理层数。0 = 不信任 X-Forwarded-For（防伪造）；
    # 直连部署保持 0；有 N 层可信反代时设为 N，将从 XFF 右侧数第 N+1 个地址作为客户端。
    trust_proxy_count: int = 0

    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", env_file=_ENV_FILE, extra="ignore")
