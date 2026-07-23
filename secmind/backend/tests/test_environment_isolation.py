from __future__ import annotations

from app.core.config import Settings


def test_default_test_settings_do_not_load_deployment_environment() -> None:
    settings = Settings()

    assert settings.app_env == "test"
    assert settings.llm_provider == "null"
    assert settings.resolved_llm_api_key is None
    assert settings.checkpoint_backend == "memory"
    assert settings.projection_enabled is False
    assert settings.qdrant_enabled is False
    assert settings.mcp_config_file is None
    assert settings.llm_max_attempts == 2
