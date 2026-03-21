"""
L1 输入安全检测
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from app.infra.metrics import (
    INPUT_BLOCKED,
    INPUT_INJECTION_DETECTED,
    INPUT_MODE,
    INPUT_PASSED,
    INPUT_PII_ANONYMIZED,
    INPUT_PII_DETECTED,
)
from app.safety.config import SafetySettings
from app.safety.enums import SafetyMode

logger = structlog.get_logger(__name__)


# ── PII 检测（正则后端，供 Presidio 降级使用）────────────────────────────────────


@dataclass
class PiiEntity:
    type: str
    text: str
    start: int
    end: int
    score: float


@dataclass
class PiiResult:
    entities: list[PiiEntity] = field(default_factory=list)
    anonymized_text: str = ""
    has_pii: bool = False


# 中文 PII 正则
_CN_PHONE = re.compile(r"1[3-9]\d{9}")
_CN_ID_CARD = re.compile(
    r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
)
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_IP = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_API_KEY = re.compile(r"(?:sk-|pk-|api[_-]?key)[a-zA-Z0-9_-]{16,}", re.IGNORECASE)

_PII_RULES: list[tuple[str, re.Pattern, str]] = [
    ("PHONE_CN", _CN_PHONE, "mask"),
    ("ID_CARD_CN", _CN_ID_CARD, "mask"),
    ("EMAIL", _EMAIL, "mask"),
    ("IP_ADDRESS", _IP, "redact"),
    ("CREDIT_CARD", _CREDIT_CARD, "mask"),
    ("API_KEY", _API_KEY, "redact"),
]

_PII_STRATEGY = {name: strategy for name, _, strategy in _PII_RULES}


class PiiDetector:
    """
    PII 检测 + 脱敏 — 正则后端。

    使用 PresidioPiiDetector（app/safety/presidio_pii.py）优先。
    本类保持作为 fallback 实现。
    """

    def __init__(self, settings: SafetySettings | None = None) -> None:
        self._settings = settings
        self._spacy_nlp = None

    async def analyze(self, text: str) -> PiiResult:
        """检测文本中的 PII"""
        if not text or not text.strip():
            return PiiResult()

        entities: list[PiiEntity] = []

        for pii_type, pattern, _ in _PII_RULES:
            for match in pattern.finditer(text):
                entities.append(
                    PiiEntity(
                        type=pii_type,
                        text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        score=0.9,
                    )
                )

        entities.sort(key=lambda e: e.start)
        if entities:
            seen = set()
            for e in entities:
                if e.type not in seen:
                    INPUT_PII_DETECTED.labels(pii_type=e.type).inc()
                    seen.add(e.type)
        return PiiResult(entities=entities, has_pii=len(entities) > 0)

    async def anonymize(self, text: str) -> str:
        """脱敏文本中的 PII"""
        if not text or not text.strip():
            return text

        result = await self.analyze(text)
        if not result.has_pii:
            return text

        seen = set()
        for e in result.entities:
            if e.type not in seen:
                INPUT_PII_ANONYMIZED.labels(pii_type=e.type).inc()
                seen.add(e.type)

        chars = list(text)
        for entity in reversed(result.entities):
            strategy = _PII_STRATEGY.get(entity.type, "mask")
            if strategy == "redact":
                placeholder = f"[{entity.type}]"
                chars[entity.start : entity.end] = list(placeholder)
            else:
                length = entity.end - entity.start
                visible = max(1, length // 4)
                if length <= visible * 2:
                    masked = entity.text[:visible] + "*" * (length - visible)
                else:
                    masked = (
                        entity.text[:visible]
                        + "*" * (length - visible * 2)
                        + entity.text[-visible:]
                    )
                chars[entity.start : entity.end] = list(masked)

        return "".join(chars)


# ── 注入检测 ────────────────────────────────────────────────────────────────────


@dataclass
class InjectionMatch:
    category: str
    pattern: str
    matched_text: str
    risk_score: float
    description: str


@dataclass
class InjectionResult:
    matches: list[InjectionMatch] = field(default_factory=list)
    max_risk_score: float = 0.0
    is_injection: bool = False


_INJECTION_PATTERNS: list[tuple[str, str, float, str]] = [
    # 指令覆盖
    (
        "instruction_override",
        r"忽略(?:所有|上述|之前|系统)?(?:指令|提示词|规则|约束)",
        9.5,
        "试图覆盖系统指令",
    ),
    (
        "instruction_override",
        r"(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:previous|above|prior|earlier|system)\s+(?:instructions?|prompts?|rules?|constraints?)",
        9.5,
        "Attempts to override system instructions",
    ),
    # 新指令注入
    (
        "new_instructions",
        r"(?:new|updated|revised|real)\s+(?:instructions?|system\s+prompt|directive)",
        8.5,
        "New instruction injection",
    ),
    # 角色劫持
    (
        "role_hijack",
        r"(?:你(?:现在|要)是|扮演|假装|you\s+are\s+now|act\s+as|pretend\s+to\s+be)",
        8.0,
        "角色劫持",
    ),
    # 敏感数据窃取
    (
        "exfil_request",
        r"(?:输出|显示|回复|打印|reveal|show|print|display)\s*(?:所有|全部)?\s*(?:系统)?(?:提示词|指令|密码|密钥|api[_-]?key|token|secret|credential)",
        9.5,
        "试图窃取系统敏感信息",
    ),
    (
        "exfil_request",
        r"(?:output|print|display|reveal|show|send|transmit)\s+(?:all\s+)?(?:api[_-]?keys?|passwords?|secrets?|credentials?|tokens?)",
        9.5,
        "Attempts to exfiltrate credentials",
    ),
    # 数据外传
    (
        "exfil_url",
        r"(?:发送|上传|post|send|upload|transmit)\s+(?:[\w\s]{0,20}\s+)?(?:到|to)\s+(https?://)",
        9.0,
        "试图将数据外传到 URL",
    ),
    # 分隔符逃逸
    (
        "delimiter_escape",
        r"[-=*]{3,}\s*(?:END|BEGIN|SYSTEM|ADMIN|ROOT)\s*[-=*]{3,}",
        8.0,
        "分隔符逃逸",
    ),
    # 经典越狱
    (
        "dan_jailbreak",
        r"(?:DAN|do\s+anything\s+now|developer\s+mode|jailbreak|越狱)",
        7.0,
        "经典越狱攻击",
    ),
    # Base64 混淆
    (
        "base64_payload",
        r"(?:base64|b64)\s*(?:解码|decode|exec|eval|run|执行)",
        7.5,
        "Base64 混淆载荷",
    ),
    # 套取系统提示词
    (
        "system_prompt_query",
        r"(?:你的(?:系统)?(?:提示词|指令|prompt|system\s+prompt)(?:.*(?:是|是什么|有哪些))?)",
        6.0,
        "套取系统提示词",
    ),
    (
        "system_prompt_query_output",
        r"(?:输出|显示|回复|打印|reveal|show|print)\s*(?:你的)?(?:系统)?(?:提示词|指令|prompt)",
        7.0,
        "试图输出系统提示词",
    ),
]


class InjectionDetector:
    """
    评分式注入检测器。

    多模式正则匹配，每条规则有独立风险分。
    累计最高风险分超过阈值时视为注入。
    """

    def __init__(self, threshold: float = 7.0) -> None:
        self._threshold = threshold
        self._compiled: list[tuple[str, re.Pattern, float, str]] = [
            (category, re.compile(pattern, re.IGNORECASE), score, desc)
            for category, pattern, score, desc in _INJECTION_PATTERNS
        ]

    async def detect(self, text: str) -> InjectionResult:
        """检测文本中的注入模式，返回所有匹配"""
        if not text or not text.strip():
            return InjectionResult()

        matches: list[InjectionMatch] = []
        for category, pattern, score, desc in self._compiled:
            for m in pattern.finditer(text):
                matches.append(
                    InjectionMatch(
                        category=category,
                        pattern=pattern.pattern,
                        matched_text=m.group(),
                        risk_score=score,
                        description=desc,
                    )
                )

        max_score = max((m.risk_score for m in matches), default=0.0)
        is_injection = max_score >= self._threshold

        if is_injection:
            risk_level = (
                "critical" if max_score >= 9.0 else "high" if max_score >= 7.0 else "medium"
            )
            INPUT_INJECTION_DETECTED.labels(risk_level=risk_level).inc()

        return InjectionResult(
            matches=matches,
            max_risk_score=max_score,
            is_injection=is_injection,
        )


# ── 输入安全编排入口 ─────────────────────────────────────────────────────────────


@dataclass
class InputFilterResult:
    is_safe: bool
    sanitized_text: str
    reason: str = ""


SAFETY_MODE = SafetyMode.FAIL_CLOSE


async def set_safety_mode(mode: SafetyMode) -> None:
    global SAFETY_MODE
    SAFETY_MODE = mode
    INPUT_MODE.set({"closed": 2, "open": 1, "monitor": 0}.get(mode.value, 2))


class SafetyInputFilter:
    """
    L1 输入安全编排入口。

    执行顺序：
    1. PII 脱敏（保留上下文，供后续 LLM 使用）
    2. 注入检测（风险分判断）

    安全模式：
    - fail_close: 检测异常时拦截（生产推荐）
    - fail_open: 检测异常时放行（开发用）
    - monitor: 仅记录日志（调试用）
    """

    def __init__(
        self,
        pii_detector: PiiDetector | None = None,
        injection_detector: InjectionDetector | None = None,
        settings: SafetySettings | None = None,
    ) -> None:
        if pii_detector is None:
            from app.safety.presidio_pii import PresidioPiiDetector

            pii_detector = PresidioPiiDetector(settings=settings)
        self._pii = pii_detector
        self._injection = injection_detector or InjectionDetector(
            threshold=settings.input_injection_threshold if settings else 7.0
        )
        self._settings = settings

    async def filter(self, question: str) -> InputFilterResult:
        """
        执行输入安全检测。

        返回 (is_safe, sanitized_text, reason)
        """
        if not question or not question.strip():
            return InputFilterResult(is_safe=True, sanitized_text=question)

        INPUT_MODE.set({"closed": 2, "open": 1, "monitor": 0}.get(SAFETY_MODE.value, 2))

        # 1. PII 脱敏
        try:
            if not self._settings or self._settings.input_pii_enabled:
                sanitized = await self._pii.anonymize(question)
            else:
                sanitized = question
        except Exception as e:
            logger.error("pii_anonymize_failed", error=str(e))
            return await self._handle_error("PII 检测服务异常", question)

        # 2. 注入检测
        try:
            if not self._settings or self._settings.input_injection_enabled:
                injection_result = await self._injection.detect(sanitized)
                if injection_result.is_injection:
                    logger.warning(
                        "injection_detected",
                        max_risk_score=injection_result.max_risk_score,
                        matches=[(m.category, m.risk_score) for m in injection_result.matches],
                    )
                    INPUT_BLOCKED.labels(reason="injection").inc()
                    return InputFilterResult(
                        is_safe=False,
                        sanitized_text=sanitized,
                        reason="请求包含不符合安全规范的内容，已拒绝。",
                    )
        except Exception as e:
            logger.error("injection_detect_failed", error=str(e))
            return await self._handle_error("注入检测服务异常", sanitized)

        INPUT_PASSED.inc()
        return InputFilterResult(is_safe=True, sanitized_text=sanitized)

    async def _handle_error(self, msg: str, original_text: str = "") -> InputFilterResult:
        if SAFETY_MODE == SafetyMode.FAIL_CLOSE:
            INPUT_BLOCKED.labels(reason="service_error").inc()
            return InputFilterResult(
                is_safe=False, sanitized_text="", reason=f"{msg}，已拒绝该请求。"
            )
        if SAFETY_MODE == SafetyMode.MONITOR:
            logger.warning("safety_filter_fallback_monitor", message=msg)
            return InputFilterResult(is_safe=True, sanitized_text=original_text)
        logger.warning("safety_filter_fallback_open", message=msg)
        return InputFilterResult(is_safe=True, sanitized_text=original_text)
