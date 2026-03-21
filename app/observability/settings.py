from __future__ import annotations

from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    sample_rate: float = 1.0
    span_store_batch_size: int = 50
    retention_days: int = 30
    price_gpt4o_per_1k_input: float = 0.0025
    price_gpt4o_per_1k_output: float = 0.01
    price_gpt4o_mini_per_1k_input: float = 0.00015
    price_gpt4o_mini_per_1k_output: float = 0.0006
