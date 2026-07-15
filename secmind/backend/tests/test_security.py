from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_optional_api_key_protects_api_routes(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path / "data",
            ledger_dir=tmp_path / "ledger",
            cors_origins=["*"],
            api_key="secret-key",
            mock_step_delay_seconds=0,
        )
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/info").status_code == 401
        assert client.get("/api/v1/info", headers={"x-api-key": "secret-key"}).status_code == 200


def test_rate_limit_returns_429(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path / "data",
            ledger_dir=tmp_path / "ledger",
            cors_origins=["*"],
            rate_limit_requests=1,
            rate_limit_window_seconds=60,
            mock_step_delay_seconds=0,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/info").status_code == 200
        assert client.get("/api/v1/info").status_code == 429
