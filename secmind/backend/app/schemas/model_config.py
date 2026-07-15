from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ModelConfigInput(BaseModel):
    provider: Literal["qwen", "dashscope", "openai-compatible"] = "qwen"
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("model contains unsupported characters")
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        return SecretStr(secret) if secret else None


class ModelConfigUpdate(ModelConfigInput):
    test_connection: bool = True


class ModelConfigResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    api_key_configured: bool
    configured: bool
    updated_at: datetime


class ModelConnectionTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int
    message: str


class ModelUsageByModel(BaseModel):
    provider: str
    model: str
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last_request_at: datetime | None = None


class ModelUsageByConversation(BaseModel):
    flow_id: str
    title: str | None = None
    models: list[str] = Field(default_factory=list)
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last_request_at: datetime | None = None


class ModelUsageResponse(BaseModel):
    period: Literal["day", "month", "total"] = "total"
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float | None = None
    currency: str | None = None
    last_request_at: datetime | None = None
    by_model: list[ModelUsageByModel] = Field(default_factory=list)
    by_conversation: list[ModelUsageByConversation] = Field(default_factory=list)
