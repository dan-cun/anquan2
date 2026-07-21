from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SecMind Backend"
    app_version: str = "0.1.0"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    api_key: SecretStr | None = None
    api_key_file: Path | None = None
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=120, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    websocket_idle_timeout_seconds: int = Field(default=300, ge=10, le=7200)
    graphql_path: str = "/graphql"
    graphql_subscription_keepalive_seconds: int = Field(default=20, ge=5, le=300)

    data_dir: Path = Path("./data")
    ledger_dir: Path | None = None
    ledger_snapshot_interval: int = 10
    mock_step_delay_seconds: float = 0.02

    # SECMIND_DATABASE_URL is the canonical application database setting.
    # runtime_database_url remains as a compatibility input during migration.
    database_url: str | None = None
    runtime_database_url: str | None = None
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=100)
    runtime_input_root: Path | None = None
    runtime_run_root: Path | None = None
    runtime_upload_root: Path | None = None
    runtime_demo_mode: bool = True
    runtime_max_steps: int = Field(default=12, ge=1, le=100)
    runtime_max_tool_calls: int = Field(default=12, ge=1, le=100)
    runtime_max_model_calls: int = Field(default=20, ge=1, le=200)
    runtime_max_runtime_seconds: int = Field(default=600, ge=10, le=7200)
    runtime_max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    runtime_max_extracted_bytes: int = Field(default=200 * 1024 * 1024, ge=1024)
    runtime_max_files: int = Field(default=10_000, ge=1)
    runtime_max_zip_ratio: int = Field(default=100, ge=1)
    event_stream_batch_size: int = Field(default=500, ge=1, le=10_000)
    event_stream_poll_interval_seconds: float = Field(default=1.0, gt=0, le=30)

    checkpoint_backend: Literal["memory", "sqlite", "postgres"] = "memory"
    checkpoint_database_url: str | None = None
    checkpoint_namespace: str = "secmind"

    projection_enabled: bool = False
    projection_batch_size: int = Field(default=500, ge=1, le=10_000)
    projection_rebuild_on_start: bool = False

    agent_max_parallel: int = Field(default=8, ge=1, le=128)
    agent_max_delegation_depth: int = Field(default=12, ge=1, le=100)

    mcp_config_file: Path | None = None
    mcp_connect_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    mcp_call_timeout_seconds: float = Field(default=300.0, gt=0, le=7200)
    mcp_refresh_interval_seconds: float = Field(default=60.0, gt=0, le=86_400)

    prompt_override_dir: Path | None = None
    prompt_workbook_path: Path | None = None
    prompt_auto_reload: bool = False

    llm_provider: str = "null"
    llm_api_key: SecretStr | None = None
    llm_api_key_file: Path | None = None
    llm_base_url: str = (
        "https://ws-6a97xnb0sh5clxp6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    llm_model: str = "qwen-plus"
    llm_planner_model: str | None = None
    llm_worker_model: str | None = None
    llm_fallback_model: str | None = None
    llm_embedding_model: str = "text-embedding-v3"
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.2

    qdrant_enabled: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_api_key_file: Path | None = None
    qdrant_collection: str = "secmind_knowledge"
    qdrant_memory_collection: str = "secmind_memory"
    qdrant_vector_size: int = Field(default=1024, ge=1, le=65_536)
    qdrant_timeout_seconds: float = Field(default=10.0, gt=0, le=300)

    cors_origins: Annotated[list[str], NoDecode] = Field(
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

    @field_validator("checkpoint_backend", mode="before")
    @classmethod
    def normalize_checkpoint_backend(cls, value: Any) -> str:
        return str(value or "memory").strip().lower()

    @field_validator("llm_api_key", "qdrant_api_key", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def normalize_llm_base_url(cls, value: Any) -> str:
        return str(value).strip().rstrip("/")

    @field_validator("qdrant_url", mode="before")
    @classmethod
    def normalize_qdrant_url(cls, value: Any) -> str:
        return str(value).strip().rstrip("/")

    @field_validator("graphql_path", mode="before")
    @classmethod
    def normalize_graphql_path(cls, value: Any) -> str:
        normalized = f"/{str(value or 'graphql').strip().strip('/')}"
        if normalized == "/":
            raise ValueError("graphql_path must not be the root path")
        return normalized

    @property
    def resolved_api_key(self) -> str | None:
        return self._secret_value(self.api_key, self.api_key_file)

    @property
    def resolved_llm_api_key(self) -> str | None:
        return self._secret_value(self.llm_api_key, self.llm_api_key_file)

    @property
    def resolved_qdrant_api_key(self) -> str | None:
        return self._secret_value(self.qdrant_api_key, self.qdrant_api_key_file)

    @property
    def resolved_llm_planner_model(self) -> str:
        return self.llm_planner_model or self.llm_model

    @property
    def resolved_llm_worker_model(self) -> str:
        return self.llm_worker_model or self.llm_model

    @property
    def resolved_llm_fallback_model(self) -> str:
        return self.llm_fallback_model or self.llm_model

    @property
    def resolved_ledger_dir(self) -> Path:
        return self.ledger_dir or self.data_dir / "ledger"

    @property
    def resolved_runtime_input_root(self) -> Path:
        return self.runtime_input_root or self.data_dir / "inputs"

    @property
    def resolved_runtime_run_root(self) -> Path:
        return self.runtime_run_root or self.data_dir / "runs"

    @property
    def resolved_runtime_upload_root(self) -> Path:
        return self.runtime_upload_root or self.data_dir / "uploads"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.runtime_database_url:
            return self.runtime_database_url
        return f"sqlite:///{(self.data_dir / 'runtime' / 'secmind.db').as_posix()}"

    @property
    def resolved_runtime_database_url(self) -> str:
        """Compatibility alias for code that has not migrated to database_url."""
        return self.resolved_database_url

    @property
    def resolved_checkpoint_database_url(self) -> str | None:
        if self.checkpoint_backend == "memory":
            return None
        return self.checkpoint_database_url or self.resolved_database_url

    def prepare_runtime_directories(self) -> None:
        for path in (
            self.resolved_runtime_input_root,
            self.resolved_runtime_run_root,
            self.resolved_runtime_upload_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        database_urls = [self.resolved_database_url, self.resolved_checkpoint_database_url]
        for database_url in filter(None, database_urls):
            sqlite_path = self._sqlite_path(database_url)
            if sqlite_path is not None:
                sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sqlite_path(database_url: str) -> Path | None:
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if database_url.startswith(prefix):
                return Path(database_url.removeprefix(prefix))
        return None

    @staticmethod
    def _secret_value(value: SecretStr | None, file_path: Path | None) -> str | None:
        if value is not None:
            return value.get_secret_value()
        if file_path is None:
            return None
        try:
            text = file_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
