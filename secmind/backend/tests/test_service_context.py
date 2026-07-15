from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from knowledge.service import QdrantKnowledgeService


def test_lifespan_injects_sqlite_checkpointer_and_live_projection(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        checkpoint_backend="sqlite",
        checkpoint_database_url=f"sqlite:///{(tmp_path / 'checkpoints.db').as_posix()}",
        projection_enabled=True,
        llm_provider="null",
    )

    with TestClient(create_app(settings)) as client:
        services = client.app.state.services
        event = services.runtime_ledger.append(
            "projection-live",
            "run.queued",
            {"objective": "audit code"},
        )

        assert type(services.checkpointer).__name__ == "AsyncSqliteSaver"
        assert services.projection is not None
        assert services.projection.offset("projection-live") == event.sequence


def test_lifespan_injects_enabled_qdrant_service(tmp_path, monkeypatch) -> None:
    fake_service = object()
    monkeypatch.setattr(
        QdrantKnowledgeService,
        "from_settings",
        lambda settings: fake_service,
    )
    settings = Settings(
        data_dir=tmp_path,
        qdrant_enabled=True,
        llm_provider="null",
    )

    with TestClient(create_app(settings)) as client:
        services = client.app.state.services

        assert services.knowledge is fake_service
        assert services.runtime.knowledge_service is fake_service
        assert services.knowledge_backend == "qdrant"
