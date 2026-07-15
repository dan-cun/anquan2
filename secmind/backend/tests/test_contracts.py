from app.core.config import Settings
from app.schemas.events import (
    WS_PROTOCOL_VERSION,
    WSClientMessageType,
    WSMessage,
    WSServerMessageType,
)
from app.schemas.runtime import AgentState, RuntimeEventType, TaskRequest


def test_agent_state_additive_contract_defaults() -> None:
    state = AgentState(run_id="run-1", task=TaskRequest(objective="audit source code"))

    assert state.knowledge_hits == []
    assert state.completed_step_ids == []
    assert state.verification_passed is None
    assert state.state_revision == 0


def test_runtime_event_names_are_unique() -> None:
    values = [event.value for event in RuntimeEventType]

    assert len(values) == len(set(values))
    assert RuntimeEventType.CONTEXT_RETRIEVED == "context.retrieved"
    assert RuntimeEventType.MEMORY_COMMITTED == "memory.committed"


def test_websocket_envelope_contract() -> None:
    message = WSMessage.event(
        WSServerMessageType.STATUS,
        flow_id="flow-1",
        payload={"stage": "plan"},
        sequence=3,
    )

    assert message.schema_version == WS_PROTOCOL_VERSION
    assert message.type == "server.status"
    assert message.sequence == 3
    assert WSClientMessageType.USER_MESSAGE == "client.user_message"


def test_preferred_database_and_model_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECMIND_DATABASE_URL", "sqlite:///from-env.db")
    from_env = Settings(_env_file=None)

    assert from_env.resolved_database_url == "sqlite:///from-env.db"

    key_file = tmp_path / "qdrant-key"
    key_file.write_text("secret-value", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path,
        database_url="sqlite:///preferred.db",
        runtime_database_url="sqlite:///legacy.db",
        checkpoint_backend="sqlite",
        llm_model="qwen-plus",
        llm_planner_model="qwen-max",
        qdrant_api_key_file=key_file,
    )

    assert settings.resolved_database_url == "sqlite:///preferred.db"
    assert settings.resolved_runtime_database_url == "sqlite:///preferred.db"
    assert settings.resolved_checkpoint_database_url == "sqlite:///preferred.db"
    assert settings.resolved_llm_planner_model == "qwen-max"
    assert settings.resolved_llm_worker_model == "qwen-plus"
    assert settings.resolved_qdrant_api_key == "secret-value"
