from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SecMind Backend"
    app_version: str = "0.1.0"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    data_dir: Path = Path("./data")
    ledger_dir: Path | None = None
    ledger_snapshot_interval: int = 10
    mock_step_delay_seconds: float = 0.02
    llm_provider: str = "null"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = (
        "https://ws-6a97xnb0sh5clxp6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.2

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SECMIND_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if value.strip() == "*":
                return ["*"]
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("cors_origins must be a list or comma-separated string")

    @field_validator("llm_provider", mode="before")
    @classmethod
    def normalize_llm_provider(cls, value: Any) -> str:
        return str(value or "null").strip().lower()

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def normalize_llm_api_key(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def normalize_llm_base_url(cls, value: Any) -> str:
        return str(value).strip().rstrip("/")

    @property
    def resolved_ledger_dir(self) -> Path:
        return self.ledger_dir or self.data_dir / "ledger"


@lru_cache
def get_settings() -> Settings:
    return Settings()
