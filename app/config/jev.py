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

    # 关键判定阈值
    safe_threshold: float = 0.50  # 安全判断阈值 (>= 视为安全)
    citation_confidence_threshold: float = 0.60  # 引用置信度阈值 (>= 视为证据支持)

    # 超时时间 (秒，收敛为 2.0s 防止热路径服务不可用时阻塞过久)
    timeout_seconds: float = 2.0

    model_config = SettingsConfigDict(env_prefix="JEV_", env_file=_ENV_FILE, extra="ignore")
