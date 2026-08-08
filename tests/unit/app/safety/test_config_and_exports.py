
from app.safety import (
    ApprovalPolicy,
    InjectionDetector,
    InputFilterResult,
    OutputFilter,
    OutputFilterResult,
    PiiDetector,
    PiiResult,
    SafetyInputFilter,
    SafetyResponse,
    ToolRegistry,
    set_safety_mode,
)
from app.safety import (
    CircuitBreakerException as ExportedBreakerException,
)
from app.safety import (
    CircuitState as ExportedCircuitState,
)
from app.safety import (
    SafetyMode as ExportedSafetyMode,
)
from app.safety import (
    ToolRisk as ExportedToolRisk,
)
from app.safety.config import CircuitBreakerSettings, SafetySettings, get_safety_settings
from app.safety.enums import CircuitState, SafetyMode, ToolRisk
from app.safety.exceptions import CircuitBreakerException


class TestSafetyEnums:
    def test_safety_mode_values(self):
        assert SafetyMode.FAIL_CLOSE.value == "fail_close"
        assert SafetyMode.FAIL_OPEN.value == "fail_open"
        assert SafetyMode.MONITOR.value == "monitor"

    def test_tool_risk_values(self):
        assert ToolRisk.LOW.value == "low"
        assert ToolRisk.MEDIUM.value == "medium"
        assert ToolRisk.HIGH.value == "high"
        assert ToolRisk.CRITICAL.value == "critical"

    def test_circuit_state_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestSafetySettings:
    def test_defaults(self):
        s = SafetySettings(_env_file=None)
        assert s.mode == SafetyMode.FAIL_CLOSE
        assert s.input_pii_enabled is True
        assert s.input_injection_enabled is True
        assert s.input_injection_threshold == 7.0
        assert s.output_pii_enabled is True
        assert s.output_sensitive_enabled is True
        assert s.tool_approval_enabled is True

    def test_env_prefix(self, monkeypatch):
        monkeypatch.setenv("SAFETY_MODE", "monitor")
        monkeypatch.setenv("SAFETY_INPUT_INJECTION_THRESHOLD", "8.5")
        s = SafetySettings()
        assert s.mode == SafetyMode.MONITOR
        assert s.input_injection_threshold == 8.5

    def test_get_safety_settings_cached(self):
        a = get_safety_settings()
        b = get_safety_settings()
        assert a is b
        get_safety_settings.cache_clear()

    def test_circuit_breaker_defaults(self):
        s = CircuitBreakerSettings(_env_file=None)
        assert s.enabled is True
        assert s.llm_failure_threshold == 5
        assert s.llm_recovery_timeout == 60
        assert s.default_timeout == 30

    def test_circuit_breaker_env(self, monkeypatch):
        monkeypatch.setenv("CB_LLM_FAILURE_THRESHOLD", "9")
        s = CircuitBreakerSettings()
        assert s.llm_failure_threshold == 9


class TestSafetyExceptions:
    def test_circuit_breaker_is_base_exception(self):
        exc = CircuitBreakerException(code=9999, message="test")
        assert isinstance(exc, Exception)
        assert exc.code == 9999
        assert str(exc) == "test"


class TestSafetyPackageExports:
    def test_all_public_names_available(self):
        for name in (
            PiiDetector,
            PiiResult,
            InjectionDetector,
            SafetyInputFilter,
            InputFilterResult,
            ToolRegistry,
            ApprovalPolicy,
            OutputFilter,
            OutputFilterResult,
            SafetyResponse,
            set_safety_mode,
        ):
            assert callable(name) or isinstance(name, type)
        assert ExportedSafetyMode is SafetyMode
        assert ExportedToolRisk is ToolRisk
        assert ExportedCircuitState is CircuitState
        assert ExportedBreakerException is CircuitBreakerException

    def test_set_safety_mode_is_callable(self):
        assert callable(set_safety_mode)
