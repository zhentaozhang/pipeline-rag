from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class OtelSettings(BaseSettings):
    """OpenTelemetry 配置（OTLP HTTP 导出，Langfuse 不支持 gRPC）"""

    enabled: bool = False
    exporter_otlp_endpoint: str = "http://localhost:4318/v1/traces"
    service_name: str = "pipeline-rag"

    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=_ENV_FILE, extra="ignore")
