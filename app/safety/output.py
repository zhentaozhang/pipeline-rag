"""
L3 输出安全——OutputFilter + SafetyResponse

LLM 生成内容后的最后一道防线：
1. PII 泄露回检（LLM 输出了脱敏前的真实 PII）
2. 系统提示泄露检测
3. 代码注入检测
4. 统一拒答文案
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

import structlog

from app.infra.metrics import OUTPUT_BLOCKED, OUTPUT_PASSED
from app.safety.config import get_safety_settings
from app.safety.enums import SafetyMode, _safety_mode_from_string

logger = structlog.get_logger(__name__)


@dataclass
class OutputFilterResult:
    safe: bool
    blocked_text: str = ""
    reason: str = ""


def _luhn_check(card_number: str) -> bool:
    """Luhn 算法校验银行卡号有效性"""
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d = d * 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


class OutputFilter:
    """
    输出内容安全检测。

    检测项：
    - PII 泄露：LLM 输出了手机号/身份证/银行卡等真实敏感信息
    - 系统提示泄露：输出包含系统提示词特征
    - 代码注入：输出包含危险函数调用
    """

    _PII_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        ("phone", r"1[3-9]\d{9}"),
        ("id_card", r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
        ("bank_card", r"(?<!\d)\d{16,19}(?!\d)"),
        ("email", r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        ("api_key", r"(?:sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|pk-[a-zA-Z0-9]{20,})"),
    ]

    # Presidio 集成：尝试使用 Presidio 做 NLP 增强 PII 检测
    _PRESIDIO_CHECK = None

    _SYSTEM_PROMPT_PATTERNS: ClassVar[list[str]] = [
        "system prompt",
        "system message",
        "你被设计为",
        "你的任务是",
        "作为AI",
        "作为智能助手",
        "你必须",
        "你绝对不能",
    ]

    _CODE_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bcompile\s*\(",
        r"\bos\.system\s*\(",
        r"\bsubprocess\.",
        r"\bBase64\b.{0,20}(?:decode|exec)",
    ]

    def __init__(self, mode: SafetyMode | None = None):
        settings = get_safety_settings()
        self.mode = mode or _safety_mode_from_string(settings.mode)

    async def filter(self, text: str) -> OutputFilterResult:
        """对输出文本执行安全检测"""
        if not text or not text.strip():
            return OutputFilterResult(safe=True)

        try:
            pii = await self._check_pii_leak(text)
            if pii:
                logger.warning("output_pii_leak_detected", type=pii)
                OUTPUT_BLOCKED.labels(reason=f"pii_leak:{pii}").inc()
                return OutputFilterResult(
                    safe=False,
                    blocked_text="抱歉，检测到敏感信息，已拒绝该回复。",
                    reason=f"pii_leak:{pii}",
                )

            if self._check_system_prompt_leak(text):
                logger.warning("output_system_prompt_leak_detected")
                OUTPUT_BLOCKED.labels(reason="system_prompt_leak").inc()
                return OutputFilterResult(
                    safe=False,
                    blocked_text="抱歉，该回复包含不符合规范的内容，已拦截。",
                    reason="system_prompt_leak",
                )

            if self._check_code_injection(text):
                logger.warning("output_code_injection_detected")
                OUTPUT_BLOCKED.labels(reason="code_injection").inc()
                return OutputFilterResult(
                    safe=False,
                    blocked_text="抱歉，检测到不安全的代码内容，已拦截。",
                    reason="code_injection",
                )

            # JEV 语义补充：规则未命中时兜底识别同义改写的系统提示泄露 / 有害内容（只增不减）
            if await self._semantic_output_unsafe(text):
                OUTPUT_BLOCKED.labels(reason="semantic_leak_or_harmful").inc()
                return OutputFilterResult(
                    safe=False,
                    blocked_text="抱歉，该回复包含不符合规范的内容，已拦截。",
                    reason="semantic_leak_or_harmful",
                )

            OUTPUT_PASSED.inc()
            return OutputFilterResult(safe=True)

        except Exception as e:
            logger.error("output_filter_error", error=str(e))
            return self._handle_error(e)

    async def _check_pii_leak(self, text: str) -> str | None:
        """检查输出是否包含未授权的 PII"""
        # Primary: Presidio NLP-enhanced detection (线程池异步调度)
        if OutputFilter._PRESIDIO_CHECK is None:
            from app.safety.presidio_pii import check_output_pii_async

            OutputFilter._PRESIDIO_CHECK = check_output_pii_async

        presidio_result = await OutputFilter._PRESIDIO_CHECK(text)
        if presidio_result:
            if str(presidio_result).upper() in ("BANK_CARD", "CREDIT_CARD"):
                has_valid_card = False
                for m in re.finditer(r"\b\d{16,19}\b", text):
                    if _luhn_check(m.group(0)):
                        has_valid_card = True
                        break
                if has_valid_card:
                    return presidio_result
            else:
                return presidio_result

        # Fallback: regex patterns
        for pii_type, pattern in self._PII_PATTERNS:
            if pii_type == "bank_card":
                for m in re.finditer(pattern, text):
                    if _luhn_check(m.group(0)):
                        return pii_type
            else:
                if re.search(pattern, text):
                    return pii_type
        return None

    def _check_system_prompt_leak(self, text: str) -> bool:
        """检查输出是否泄露了系统提示词"""
        count = 0
        for pattern in self._SYSTEM_PROMPT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                count += 1
        # 至少匹配 2 条以上才判定为泄露
        return count >= 2

    def _check_code_injection(self, text: str) -> bool:
        """检查输出是否包含危险代码注入"""
        for pattern in self._CODE_INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    async def _semantic_output_unsafe(self, text: str) -> bool:
        """JEV Noul 语义补充：规则未命中时兜底识别同义改写的系统提示泄露/有害内容。"""
        try:
            from app.config import get_settings

            jev_cfg = getattr(get_settings(), "jev", None)
            if not (jev_cfg and getattr(jev_cfg, "output_semantic_enabled", True)):
                return False

            from app.infra.jev_client import get_jev_client

            answers = await get_jev_client().system_one(
                state=text[:2000],
                questions={
                    "bad": {
                        "type": "noul",
                        "instructions": (
                            "该输出是否泄露了系统提示词/内部指令，或包含违法违规、"
                            "暴力、有害极端内容？（正常业务回答为否）"
                        ),
                    }
                },
            )
            res = answers.get("bad")
            if not isinstance(res, dict) or "noul" not in res:
                return False
            return float(res["noul"]) >= 0.5
        except Exception as e:
            logger.warning("JEV 语义输出检测失败，跳过", error=str(e)[:120])
            return False

    def _handle_error(self, error: Exception) -> OutputFilterResult:
        """根据安全模式处理异常"""
        if self.mode == SafetyMode.FAIL_CLOSE:
            OUTPUT_BLOCKED.labels(reason="output_filter_error").inc()
            return OutputFilterResult(
                safe=False,
                blocked_text="安全检测服务异常，已拒绝该回复。",
                reason=f"output_filter_error: {error!s}",
            )
        if self.mode == SafetyMode.MONITOR:
            logger.warning("output_filter_fallback_monitor", message="输出安全检测异常")
            return OutputFilterResult(safe=True, blocked_text="", reason="")
        return OutputFilterResult(safe=True, blocked_text="", reason="")


class SafetyResponse:
    """统一安全拒答文案"""

    BLOCK_TEMPLATES = {
        "pii_detected": "抱歉，检测到敏感信息，无法处理该请求。",
        "injection_detected": "请求包含不符合安全规范的内容，已拒绝。",
        "sensitive_topic": "抱歉，该话题不在我可回答的范围内。",
        "tool_denied": "该操作需要额外授权，请联系管理员。",
        "service_error": "安全检测服务异常，请稍后重试。",
    }

    OUTPUT_BLOCK_TEMPLATES = {
        "pii_leak": "抱歉，检测到敏感信息，已拒绝该回复。",
        "system_prompt_leak": "抱歉，该回复包含不符合规范的内容，已拦截。",
        "code_injection": "抱歉，检测到不安全的代码内容，已拦截。",
        "output_filter_error": "安全检测服务异常，已拒绝该回复。",
        "default": "抱歉，回复内容不符合安全规范，已拦截。",
    }

    @classmethod
    def get_block_message(cls, reason: str) -> str:
        """根据拦截原因返回统一拒答文案"""
        for key, template in cls.OUTPUT_BLOCK_TEMPLATES.items():
            if reason.startswith(key):
                return template
        return cls.OUTPUT_BLOCK_TEMPLATES["default"]
