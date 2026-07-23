from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Test configuration must be selected before importing Settings or app.main.
# Preserve opt-in integration test settings, but discard deployment SECMIND_* values.
for _name in tuple(os.environ):
    if _name.startswith("SECMIND_") and not _name.startswith("SECMIND_TEST_"):
        os.environ.pop(_name, None)
os.environ["SECMIND_SETTINGS_ENV_FILE"] = str(Path(__file__).resolve().parents[1] / ".env.test")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        ledger_dir=tmp_path / "ledger",
        cors_origins=["*"],
        llm_provider="null",
        llm_api_key="",
        mock_step_delay_seconds=0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
