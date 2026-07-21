from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.schemas.events import (
    WS_PROTOCOL_VERSION,
    WSClientMessageType,
    WSMessage,
    WSServerMessageType,
)
from app.schemas.runtime import (
    DECISION_REQUIRED_EVENT_TYPES,
    EVENT_CONTRACT_VERSION,
    TOOL_TERMINAL_EVENT_TYPES,
    AgentState,
    DecisionKind,
    EventCategory,
    EventContext,
    EventEnvelope,
    RuntimeEventType,
    TaskRequest,
    VerificationVerdict,
)


def test_agent_state_additive_contract_defaults() -> None:
    state = AgentState(run_id="run-1", task=TaskRequest(objective="audit source code"))

    assert state.knowledge_hits == []
    assert state.completed_step_ids == []
    assert state.verification_passed is None
    assert state.state_revision == 0


def test_task_request_accepts_short_non_blank_unicode_objective() -> None:
    assert TaskRequest(objective="你好").objective == "你好"

    with pytest.raises(ValueError, match="objective must not be blank"):
        TaskRequest(objective="   ")


def test_runtime_event_names_are_unique() -> None:
    values = [event.value for event in RuntimeEventType]

    assert len(values) == len(set(values))
    assert RuntimeEventType.CONTEXT_RETRIEVED == "context.retrieved"
    assert RuntimeEventType.MEMORY_COMMITTED == "memory.committed"


def test_runtime_event_contract_covers_graph_and_flow_events() -> None:
    required = {
        "approval.invalid",
        "approval.preflight_denied",
        "context.retrieved",
        "input.approval_response",
        "input.user_message",
        "interrupt.approval_required",
        "memory.candidate",
        "memory.commit_failed",
        "memory.committed",
        "observation.missing",
        "step.blocked",
        "step.denied",
        "step.selection_complete",
        "tool.replayed",
        "agent.delegated",
        "agent.message",
        "mcp.capabilities_updated",
        "plan.revised",
        "prompt.imported",
        "decision.recorded",
        "agent.resumed",
        "tool.timed_out",
        "tool.blocked",
        "verification.started",
        "context.compressed",
        "loop.detected",
        "circuit.opened",
    }

    assert required <= {event.value for event in RuntimeEventType}


def test_event_envelope_exposes_public_decision_without_private_reasoning() -> None:
    envelope = EventEnvelope(
        event_id="event-1",
        run_id="run-1",
        sequence=4,
        event_type=RuntimeEventType.DECISION_RECORDED,
        timestamp=datetime.now(UTC),
        actor="primary_agent",
        context=EventContext(
            flow_id="flow-1",
            correlation_id="operation-1",
            decision_id="decision-1",
        ),
        payload={
            "decision": {
                "decision_id": "decision-1",
                "kind": DecisionKind.TOOL,
                "goal": "验证授权目标的服务暴露面",
                "decision": "调用 mcp:scanner:scan",
                "rationale_summary": "现有证据缺少端口状态，扫描可直接补齐该证据。",
                "expected_outcome": "获得带时间戳的端口证据",
                "risk_summary": "只读探测，范围限制为已授权目标。",
            }
        },
    )

    assert envelope.schema_version == EVENT_CONTRACT_VERSION
    assert envelope.category == EventCategory.DECISION
    assert envelope.decision is not None
    assert envelope.decision.kind == DecisionKind.TOOL
    assert envelope.decision.rationale_summary.startswith("现有证据")
    assert envelope.model_dump().get("chain_of_thought") is None


def test_operation_ordering_contract_sets_are_frozen() -> None:
    assert {
        "agent.delegated",
        "agent.stop_requested",
        "agent.completed",
        "tool.started",
        "run.completed",
    } == DECISION_REQUIRED_EVENT_TYPES
    assert {
        "tool.completed",
        "tool.failed",
        "tool.timed_out",
        "tool.cancelled",
        "tool.blocked",
    } == TOOL_TERMINAL_EVENT_TYPES
    assert {item.value for item in VerificationVerdict} == {
        "confirmed",
        "rejected",
        "inconclusive",
    }


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
        graphql_path="graphql/",
        agent_max_parallel=16,
        mcp_config_file=tmp_path / "mcp.json",
    )

    assert settings.resolved_database_url == "sqlite:///preferred.db"
    assert settings.resolved_runtime_database_url == "sqlite:///preferred.db"
    assert settings.resolved_checkpoint_database_url == "sqlite:///preferred.db"
    assert settings.resolved_llm_planner_model == "qwen-max"
    assert settings.resolved_llm_worker_model == "qwen-plus"
    assert settings.resolved_qdrant_api_key == "secret-value"
    assert settings.graphql_path == "/graphql"
    assert settings.agent_max_parallel == 16
    assert settings.mcp_config_file == tmp_path / "mcp.json"
