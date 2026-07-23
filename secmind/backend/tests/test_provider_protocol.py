import json

import pytest
from pydantic import ValidationError

from agents.chains import AgentMessageChain
from app.schemas.agents import AgentRole
from app.schemas.provider import (
    AgentFinalReport,
    AgentObservation,
    ProviderMessage,
    ProviderToolCall,
    ProviderToolResult,
)
from llm.provider_request import ProviderRequest


def native_call(call_id: str = "call-1") -> ProviderToolCall:
    return ProviderToolCall.create(
        call_id=call_id,
        name="scan_workspace",
        arguments={"target": "."},
    )


def test_provider_request_accepts_a_complete_native_tool_call_exchange() -> None:
    request = ProviderRequest(
        model="test-model",
        messages=[
            ProviderMessage(role="user", content="Inspect the workspace"),
            ProviderMessage(role="assistant", content=None, tool_calls=[native_call()]),
            ProviderToolResult(tool_call_id="call-1", content='{"status":"ok"}').as_message(),
            ProviderMessage(role="assistant", content="Inspection completed"),
        ],
    )

    payload = request.payload()
    assert payload["messages"][1]["tool_calls"][0]["id"] == "call-1"
    assert payload["messages"][1]["tool_calls"][0]["type"] == "function"
    assert payload["messages"][2] == {
        "role": "tool",
        "content": '{"status":"ok"}',
        "tool_call_id": "call-1",
    }


@pytest.mark.parametrize(
    "messages",
    [
        [
            ProviderMessage(role="user", content="Inspect"),
            ProviderToolResult(tool_call_id="fabricated", content="not native").as_message(),
        ],
        [
            ProviderMessage(role="assistant", content=None, tool_calls=[native_call("call-1")]),
            ProviderToolResult(tool_call_id="call-2", content="wrong call").as_message(),
        ],
        [ProviderMessage(role="assistant", content=None, tool_calls=[native_call("unresolved")])],
    ],
)
def test_provider_request_rejects_orphaned_mismatched_or_unresolved_tool_messages(
    messages: list[ProviderMessage],
) -> None:
    with pytest.raises(ValidationError, match="tool_call_id|unresolved"):
        ProviderRequest(model="test-model", messages=messages)


def test_provider_message_rejects_tool_role_without_a_native_call_id() -> None:
    with pytest.raises(ValidationError, match="tool messages require tool_call_id"):
        ProviderMessage(role="tool", content="fabricated observation")


def test_agent_message_chain_rejects_fabricated_tool_results() -> None:
    chain = AgentMessageChain(
        run_id="run-1",
        flow_id="flow-1",
        agent_instance_id="agent-1",
        agent_role=AgentRole.CODER,
    )
    chain.append("user", "Inspect")

    with pytest.raises(ValueError, match="unknown or already resolved"):
        chain.append("tool", "fabricated", tool_call_id="fake-call")


def test_agent_delegation_is_serialized_as_observation_and_evidence() -> None:
    report = AgentFinalReport(
        agent_instance_id="agent-coder-1",
        task_id="task-1",
        status="completed",
        summary="Source scan completed",
        evidence_ids=["evidence-1"],
    )
    observation = AgentObservation(
        source="agent",
        source_id=report.agent_instance_id,
        summary=report.summary,
        status=report.status,
        evidence_ids=report.evidence_ids,
        final_report=report,
    )

    message = observation.as_provider_message()
    body = json.loads(message.content)
    assert message.role == "user"
    assert message.tool_call_id is None
    assert message.tool_calls == []
    assert body["observation_type"] == "agent_observation"
    assert body["evidence_ids"] == ["evidence-1"]
    assert body["final_report"]["report_type"] == "agent_final_report"
