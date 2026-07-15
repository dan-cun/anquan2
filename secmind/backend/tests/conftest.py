from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
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
