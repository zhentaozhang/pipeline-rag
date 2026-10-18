"""
JEV 本地 System 1 判断模型服务配置
"""

import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE

logger = logging.getLogger(__name__)

# 这 5 个 flag 决定"评测指标由谁判定"。按产品约束，评测必须锁定单一强 LLM 裁判：
# JEV 与 LLM 双裁判会让指标失去可比性（不同裁判的满分/尺度不同），因此这里默认关，
# 且即便 env 里写成 true 也会被强制降级并告警（见 model_validator）。
_EVALUATION_FLAGS = (
    "faithfulness_eval_enabled",
    "answer_relevancy_enabled",
    "answer_correctness_enabled",
    "context_precision_enabled",
    "context_recall_enabled",
)


class JEVSettings(BaseSettings):
    """JEV 本地服务全局配置"""

    # 服务地址（如果在同一 Docker 网络中为 http://jev-service:8080，本地调试为 http://localhost:8085 或 http://localhost:8080）
    base_url: str = "http://localhost:8085"

    # 各环节独立开关（支持随时无缝回退到旧实现）
    guardrail_enabled: bool = True  # M2: 安全护栏深度检测
    intent_detection_enabled: bool = True  # M3/M4: 意图分类与分流
    navigation_intent_enabled: bool = True  # M5: 文档导航意图识别
    # 引用真实性审计：默认关。实测（24 题 + 48 例标定）JEV 路径 p50 3.73s / 准确率 0.840，
    # LLM 审计 p50 0.78s / 准确率 1.000；且真实多条款回答的分数集中在 0.4 附近，
    # 只能升级给 LLM，等于白花 2~4s。保留该开关以便在"高置信引用"场景做加速档。
    citation_verify_enabled: bool = False  # M6: 引用真实性审计（JEV 加速档，默认关）
    faithfulness_eval_enabled: bool = False  # M7: 忠实度评测（禁止 JEV 接管，见 _EVALUATION_FLAGS）
    answer_relevancy_enabled: bool = False  # M8: 答案相关性评测（禁止 JEV 接管）
    answer_correctness_enabled: bool = False  # M8b: 答案正确性评测（禁止 JEV 接管）
    context_precision_enabled: bool = False  # M9: 检索精度评测（禁止 JEV 接管）
    context_recall_enabled: bool = False  # M9: 检索召回评测（禁止 JEV 接管）
    structure_ambiguity_enabled: bool = False  # 文档结构歧义消解（A/B 实测 JEV acc 0.73 < LLM 1.00，默认走 LLM；开启后 JEV 加速但精度下降）
    evidence_sufficiency_enabled: bool = True  # 纠错检索：证据充分性判定（noul）
    quality_eval_enabled: bool = True  # 回答质量审核（score）
    injection_semantic_enabled: bool = True  # 语义注入补充检测（noul）
    output_semantic_enabled: bool = True  # 输出语义泄露/有害补充检测（noul）
    tool_risk_semantic_enabled: bool = True  # 工具调用参数级风险（noul）

    @model_validator(mode="after")
    def _evaluation_is_llm_only(self) -> "JEVSettings":
        """评测类 flag 一律强制关闭：老 .env 里写着 true 也不能让 JEV 接管判分。"""
        forced = [name for name in _EVALUATION_FLAGS if getattr(self, name)]
        if forced:
            logger.warning(
                "JEV 被配置为接管评测指标，已强制关闭（评测只允许单一 LLM 裁判）: %s",
                ",".join(forced),
            )
            for name in forced:
                setattr(self, name, False)
        return self

    # 关键判定阈值
    safe_threshold: float = 0.50  # 安全判断阈值 (>= 视为安全)
    citation_confidence_threshold: float = 0.60  # 引用置信度阈值 (>= 视为证据支持)

    # 置信度带（cascade）：JEV 仅在高置信时直接决策，落入灰区则升级到既有 LLM/规则通道。
    # 护栏（yes=有风险）：有风险概率 >= high 才高置信拦截；判 no 且概率 <= low 视为高置信无风险；
    #                    其余（灰区 / 低置信 yes / 分布分裂）视为不确定 -> 升级，安全侧永不静默降级。
    guardrail_review_low: float = 0.35
    guardrail_review_high: float = 0.65
    # 引用核验（noul 为"证据支持"概率）：>= citation_confidence_threshold 视为高置信支持、
    # 跳过 LLM 审计；低于阈值的**一律**升级给 LLM 判定，绝不由 1.5B 模型直接给用户扣
    # "引用不支持"的帽子。理由（2026-10-18 标定，48 例确定性样本）：grounded 最低 0.01、
    # fabricated 最高 0.52，AUC 0.974 但没有阈值能把两类分开 —— JEV 能筛、不能判。
    # citation_review_low 仅为历史字段保留，不再参与判定。
    citation_review_low: float = 0.45  # deprecated: 见上，判定已统一由 LLM 给出

    # 超时时间 (秒)
    timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(env_prefix="JEV_", env_file=_ENV_FILE, extra="ignore")
