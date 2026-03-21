"""
Presidio-based PII detection and anonymization.

Primary: presidio-analyzer + presidio-anonymizer with custom Chinese recognizers.
Fallback: regex-based detection (when Presidio/spaCy model unavailable).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

from app.safety.input import (
    PiiDetector as RegexPiiDetector,
)
from app.safety.input import (
    PiiEntity,
    PiiResult,
)

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine, RecognizerResult
    from presidio_anonymizer import AnonymizerEngine

logger = structlog.get_logger(__name__)

_PRESIDIO_AVAILABLE = False
_SANDBOX_NLP_ENGINE: Any = None

try:
    # Presidio uses pydantic v1-style field names (model_name) that trigger
    # pydantic v2 protected_namespace warnings — suppress at import time.
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*Field.*has conflict with protected namespace.*"
        )
        from presidio_analyzer import (
            AnalyzerEngine as _AnalyzerEngine,
        )
        from presidio_analyzer import (
            Pattern as _Pattern,
        )
        from presidio_analyzer import (
            PatternRecognizer as _PatternRecognizer,
        )
        from presidio_anonymizer import AnonymizerEngine as _AnonymizerEngine

    _PRESIDIO_AVAILABLE = True
except ImportError:
    logger.info("presidio not installed, using regex fallback for PII")

# ── Custom Chinese entity recognizers ───────────────────────────────────────────

_CN_PHONE_REGEX = re.compile(r"1[3-9]\d{9}")
_CN_ID_CARD_REGEX = re.compile(
    r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
)
_API_KEY_REGEX = re.compile(r"(?:sk-|pk-|api[_-]?key)[a-zA-Z0-9_-]{16,}", re.IGNORECASE)


def _build_custom_recognizers() -> list[Any]:
    """Build custom Presidio recognizers for Chinese PII entities."""
    if not _PRESIDIO_AVAILABLE:
        return []

    cn_phone = _PatternRecognizer(
        supported_entity="CN_PHONE",
        name="CnPhoneRecognizer",
        patterns=[
            _Pattern(name="cn_phone", regex=_CN_PHONE_REGEX.pattern, score=0.95),
        ],
        context=["phone", "手机", "mobile", "电话", "号码"],
    )

    cn_id_card = _PatternRecognizer(
        supported_entity="CN_ID_CARD",
        name="CnIdCardRecognizer",
        patterns=[
            _Pattern(name="cn_id_card", regex=_CN_ID_CARD_REGEX.pattern, score=0.95),
        ],
        context=["id", "身份证", "证件", "identity", "ID"],
    )

    api_key = _PatternRecognizer(
        supported_entity="API_KEY",
        name="ApiKeyRecognizer",
        patterns=[
            _Pattern(name="api_key", regex=_API_KEY_REGEX.pattern, score=0.9),
        ],
        context=["api", "key", "密钥", "token", "secret"],
    )

    return [cn_phone, cn_id_card, api_key]


def _get_or_init_nlp_engine() -> Any:
    """Lazy-init a lightweight NLP engine for Presidio."""
    global _SANDBOX_NLP_ENGINE
    if _SANDBOX_NLP_ENGINE is not None:
        return _SANDBOX_NLP_ENGINE

    if not _PRESIDIO_AVAILABLE:
        return None

    try:
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        _SANDBOX_NLP_ENGINE = provider.create_engine()
        return _SANDBOX_NLP_ENGINE
    except Exception as exc:
        logger.warning("failed to init Presidio NLP engine", error=str(exc), exc_info=True)
        return None


_AnalyzerEngineInstance: AnalyzerEngine | None = None


def get_analyzer_engine() -> Any | None:
    """Get or create a shared AnalyzerEngine with custom recognizers."""
    global _AnalyzerEngineInstance
    if _AnalyzerEngineInstance is not None:
        return _AnalyzerEngineInstance

    if not _PRESIDIO_AVAILABLE:
        return None

    nlp_engine = _get_or_init_nlp_engine()
    if nlp_engine is None:
        return None

    try:
        engine = _AnalyzerEngine(
            nlp_engine=nlp_engine,
            default_score_threshold=0.5,
        )
        for rec in _build_custom_recognizers():
            engine.registry.add_recognizer(rec)
        _AnalyzerEngineInstance = engine
        return engine
    except Exception as exc:
        logger.warning("failed to create AnalyzerEngine", error=str(exc), exc_info=True)
        return None


_AnonymizerEngineInstance: AnonymizerEngine | None = None


def get_anonymizer_engine() -> Any | None:
    """Get or create a shared AnonymizerEngine."""
    global _AnonymizerEngineInstance
    if _AnonymizerEngineInstance is not None:
        return _AnonymizerEngineInstance

    if not _PRESIDIO_AVAILABLE:
        return None

    try:
        engine = _AnonymizerEngine()
        _AnonymizerEngineInstance = engine
        return engine
    except Exception as exc:
        logger.warning("failed to create AnonymizerEngine", error=str(exc), exc_info=True)
        return None


# ── Presidio PII Detector ───────────────────────────────────────────────────────


_PRESIDIO_TO_INTERNAL_TYPE = {
    "CN_PHONE": "PHONE_CN",
    "CN_ID_CARD": "ID_CARD_CN",
    "EMAIL_ADDRESS": "EMAIL",
    "IP_ADDRESS": "IP_ADDRESS",
    "CREDIT_CARD": "CREDIT_CARD",
    "API_KEY": "API_KEY",
    "PHONE_NUMBER": "PHONE_CN",
    "URL": "URL",
}


# spaCy NER entity types — noisy on Chinese text with en model, skip for input
_SPACY_NER_TYPES = frozenset(
    {
        "PERSON",
        "LOCATION",
        "ORGANIZATION",
        "DATE_TIME",
        "DATE",
        "TIME",
        "GPE",
        "FAC",
        "NORP",
    }
)


def _to_internal_type(entity_type: str) -> str:
    return _PRESIDIO_TO_INTERNAL_TYPE.get(entity_type, entity_type)


class PresidioPiiDetector(RegexPiiDetector):
    """
    PII detector using Presidio as primary engine, with regex fallback.

    Benefits over pure regex:
    - Context-aware detection via spaCy NER (PERSON, LOCATION, etc.)
    - Structured recognizer registry with confidence scoring
    - Built-in anonymizer with multiple operators
    - Extensible custom recognizer framework
    """

    def __init__(self, settings: Any = None) -> None:
        super().__init__(settings=settings)
        self._analyzer = get_analyzer_engine()
        self._anonymizer = get_anonymizer_engine()
        self._has_presidio = self._analyzer is not None and self._anonymizer is not None
        if self._has_presidio:
            logger.info("presidio_pii_detector_initialized")
        else:
            logger.info("presidio_unavailable_using_regex_fallback")

    async def analyze(self, text: str) -> PiiResult:
        if not text or not text.strip():
            return PiiResult()

        if self._has_presidio:
            return await self._analyze_presidio(text)

        return await super().analyze(text)

    async def _analyze_presidio(self, text: str) -> PiiResult:
        if self._analyzer is None:
            raise RuntimeError("Presidio analyzer not initialized")
        try:
            raw_results = self._analyzer.analyze(text=text, language="en")
        except Exception as exc:
            logger.error("presidio_analyze_failed", error=str(exc), exc_info=True)
            return await super().analyze(text)

        # 1. Remove low-confidence and spaCy NER (noisy on Chinese with en model)
        filtered = [
            r for r in raw_results if r.score >= 0.5 and r.entity_type not in _SPACY_NER_TYPES
        ]

        # 2. Remove built-in false positives that overlap with our custom recognizers
        custom_types = {"CN_PHONE", "CN_ID_CARD", "API_KEY"}
        has_custom: set[str] = set()
        for r in filtered:
            if r.entity_type in custom_types:
                has_custom.add(r.entity_type)

        # 3. Filter down: remove builtin guesses that overlap with strong custom hits
        cleaned: list[RecognizerResult] = []
        for r in filtered:
            if _to_internal_type(r.entity_type) == r.entity_type:
                pass
            elif r.entity_type == "DATE_TIME" and (
                "CN_ID_CARD" in has_custom or "CN_PHONE" in has_custom
            ):
                text_snippet = text[r.start : r.end]
                if _CN_PHONE_REGEX.fullmatch(text_snippet) or _CN_ID_CARD_REGEX.fullmatch(
                    text_snippet
                ):
                    continue
            cleaned.append(r)

        custom_entity_map = {
            "CN_PHONE": ("PHONE_CN", "mask"),
            "CN_ID_CARD": ("ID_CARD_CN", "mask"),
            "API_KEY": ("API_KEY", "redact"),
        }

        entities: list[PiiEntity] = []
        for r in cleaned:
            entity_type, strategy = custom_entity_map.get(
                r.entity_type,
                (_to_internal_type(r.entity_type), "mask"),
            )
            entities.append(
                PiiEntity(
                    type=entity_type,
                    text=text[r.start : r.end],
                    start=r.start,
                    end=r.end,
                    score=r.score,
                )
            )

        entities.sort(key=lambda e: e.start)
        entities = self._deduplicate(entities)

        if entities:
            from app.infra.metrics import INPUT_PII_DETECTED

            seen = set()
            for e in entities:
                if e.type not in seen:
                    INPUT_PII_DETECTED.labels(pii_type=e.type).inc()
                    seen.add(e.type)

        return PiiResult(entities=entities, has_pii=len(entities) > 0)

    async def anonymize(self, text: str) -> str:
        if not text or not text.strip():
            return text

        if self._has_presidio:
            return await self._anonymize_presidio(text)
        return await super().anonymize(text)

    async def _anonymize_presidio(self, text: str) -> str:
        if self._analyzer is None:
            raise RuntimeError("Presidio analyzer not initialized")
        if self._anonymizer is None:
            raise RuntimeError("Presidio anonymizer not initialized")

        result = await self._analyze_presidio(text)
        if not result.has_pii:
            return text

        # Build presidio-style AnalyzerResults from our entities
        from presidio_analyzer import RecognizerResult

        reverse_map = {v: k for k, v in _PRESIDIO_TO_INTERNAL_TYPE.items()}
        presidio_results: list[RecognizerResult] = []
        for e in result.entities:
            presidio_type = reverse_map.get(e.type, e.type)
            presidio_results.append(
                RecognizerResult(
                    entity_type=presidio_type,
                    start=e.start,
                    end=e.end,
                    score=e.score,
                )
            )

        from app.infra.metrics import INPUT_PII_ANONYMIZED

        seen = set()
        for e in result.entities:
            if e.type not in seen:
                INPUT_PII_ANONYMIZED.labels(pii_type=e.type).inc()
                seen.add(e.type)

        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=presidio_results,
        )
        return anonymized.text

    @staticmethod
    def _deduplicate(entities: list[PiiEntity]) -> list[PiiEntity]:
        if not entities:
            return entities
        result: list[PiiEntity] = [entities[0]]
        for e in entities[1:]:
            last = result[-1]
            if e.start >= last.end or e.end > last.end:
                result.append(e)
        return result


# ── Output PII detector (for OutputFilter) ──────────────────────────────────────


def check_output_pii(text: str) -> str | None:
    """Check if text contains PII in output. Returns PII type or None."""
    if not text or not text.strip():
        return None

    if _PRESIDIO_AVAILABLE:
        engine = get_analyzer_engine()
        if engine is not None:
            try:
                results = engine.analyze(text=text, language="en")
                for r in results:
                    if r.score >= 0.8 and r.entity_type not in _SPACY_NER_TYPES:
                        pii_type = _to_internal_type(r.entity_type)
                        if pii_type not in ("URL",):
                            return pii_type
            except Exception:
                logger.warning("output PII check failed", exc_info=True)

    # Fallback: check common PII patterns
    if _CN_PHONE_REGEX.search(text):
        return "PHONE_CN"
    if _CN_ID_CARD_REGEX.search(text):
        return "ID_CARD_CN"
    if _API_KEY_REGEX.search(text):
        return "API_KEY"
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
        return "EMAIL"
    if re.search(r"\d{16,19}", text):
        return "BANK_CARD"
    return None
