from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class OtelSettings(BaseSettings):
    """OpenTelemetry 配置（OTLP HTTP 导出，Langfuse 不支持 gRPC）"""

    enabled: bool = False
    exporter_otlp_endpoint: str = "http://localhost:4318/v1/traces"
    # 显式 OTLP 头（逗号分隔 k=v）；留空且 Langfuse 启用时自动派生 Basic auth
    exporter_otlp_headers: str = ""
    service_name: str = "pipeline-rag"
    # 基础设施 span 采样率（1.0=全采；0.0=不采）
    sample_rate: float = 1.0

    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=_ENV_FILE, extra="ignore")
