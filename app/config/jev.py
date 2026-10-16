"""
JEV 本地 System 1 判断模型服务配置
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class JEVSettings(BaseSettings):
    """JEV 本地服务全局配置"""

    # 服务地址（如果在同一 Docker 网络中为 http://jev-service:8080，本地调试为 http://localhost:8085 或 http://localhost:8080）
    base_url: str = "http://localhost:8085"

    # 各环节独立开关（支持随时无缝回退到旧实现）
    guardrail_enabled: bool = True  # M2: 安全护栏深度检测
    intent_detection_enabled: bool = True  # M3/M4: 意图分类与分流
    navigation_intent_enabled: bool = True  # M5: 文档导航意图识别
    citation_verify_enabled: bool = True  # M6: 引用真实性审计
    faithfulness_eval_enabled: bool = True  # M7: 忠实度评测
    answer_relevancy_enabled: bool = True  # M8: 答案相关性评测
    answer_correctness_enabled: bool = True  # M8b: 答案正确性评测
    context_precision_enabled: bool = True  # M9: 检索精度评测
    context_recall_enabled: bool = True  # M9: 检索召回评测
    structure_ambiguity_enabled: bool = False  # 文档结构歧义消解（A/B 实测 JEV acc 0.73 < LLM 1.00，默认走 LLM；开启后 JEV 加速但精度下降）
    evidence_sufficiency_enabled: bool = True  # 纠错检索：证据充分性判定（noul）
    quality_eval_enabled: bool = True  # 回答质量审核（score）
    injection_semantic_enabled: bool = True  # 语义注入补充检测（noul）
    output_semantic_enabled: bool = True  # 输出语义泄露/有害补充检测（noul）
    tool_risk_semantic_enabled: bool = True  # 工具调用参数级风险（noul）

    # 关键判定阈值
    safe_threshold: float = 0.50  # 安全判断阈值 (>= 视为安全)
    citation_confidence_threshold: float = 0.60  # 引用置信度阈值 (>= 视为证据支持)

    # 置信度带（cascade）：JEV 仅在高置信时直接决策，落入灰区则升级到既有 LLM/规则通道。
    # 护栏（yes=有风险）：有风险概率 >= high 才高置信拦截；判 no 且概率 <= low 视为高置信无风险；
    #                    其余（灰区 / 低置信 yes / 分布分裂）视为不确定 -> 升级，安全侧永不静默降级。
    guardrail_review_low: float = 0.35
    guardrail_review_high: float = 0.65
    # 引用核验（noul 为"证据支持"概率）：< low 明确不支持；>= citation_confidence_threshold
    #                                    明确支持；[low, threshold) 为灰区 -> 整轮升级到既有 LLM 审计。
    citation_review_low: float = 0.45

    # 超时时间 (秒，收敛为 2.0s 防止热路径服务不可用时阻塞过久)
    timeout_seconds: float = 2.0

    model_config = SettingsConfigDict(env_prefix="JEV_", env_file=_ENV_FILE, extra="ignore")
