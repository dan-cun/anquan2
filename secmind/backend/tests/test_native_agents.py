from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

import pytest

from agents.actions import AgentActionError, AgentActionType, parse_agent_action
from agents.dispatcher import AgentDispatcher
from agents.native import StaticPromptResolver
from agents.registry import ROLE_DESCRIPTORS, build_native_agent_registry
from app.schemas.agents import AgentMessageKind, AgentRole, AgentStatus, AgentTask
from app.schemas.runtime import EventContext
from app.schemas.tools import (
    ToolExecutionStatus,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from llm.base import LLMMessage, LLMProvider, LLMResponse


def action(action_type: str, **values: Any) -> str:
    return json.dumps({"action": action_type, **values})


class ScriptedModel(LLMProvider):
    name = "scripted"

    def __init__(self, scripts: dict[AgentRole, list[str]]) -> None:
        self.scripts = {role: deque(items) for role, items in scripts.items()}
        self.calls: list[AgentRole] = []
        self.message_snapshots: list[list[LLMMessage]] = []

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        role = AgentRole(str(kwargs["stage"]).removeprefix("agent."))
        self.calls.append(role)
        self.message_snapshots.append(messages)
        if not self.scripts[role]:
            raise AssertionError(f"No scripted response remains for {role.value}")
        return LLMResponse(
            content=self.scripts[role].popleft(),
            model=f"model-{kwargs['model_profile']}",
            provider=self.name,
        )


class RecordingGateway:
    def __init__(self) -> None:
        self.invocations: list[UnifiedToolInvocation] = []

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        self.invocations.append(invocation)
        return UnifiedToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            text="Static analysis completed",
            artifact_refs=["artifact-code-report"],
            evidence_ids=["evidence-code"],
        )


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any], str]] = []

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        context: EventContext | None = None,
    ) -> None:
        self.events.append((event_type, payload, actor))


def test_action_parser_accepts_fenced_json_and_rejects_prose() -> None:
    parsed = parse_agent_action(
        "```json\n"
        + action("delegate", role="coder", objective="Create a scanner")
        + "\n```"
    )

    assert parsed.action == AgentActionType.DELEGATE
    assert parsed.role == AgentRole.CODER
    with pytest.raises(AgentActionError):
        parse_agent_action("I would call the coder next.")


def test_registry_contains_every_frozen_native_role() -> None:
    model = ScriptedModel({})
    registry = build_native_agent_registry(model=model, prompts=StaticPromptResolver())

    assert {item.role for item in ROLE_DESCRIPTORS} == set(AgentRole)
    assert {item.role for item in registry.descriptors()} == set(AgentRole)
    assert registry.descriptor(AgentRole.PRIMARY_AGENT).model_profile == "planner"
    assert registry.subgraph(AgentRole.CODER).graph.get_graph().nodes.keys() >= {
        "__start__",
        "execute_agent",
        "__end__",
    }


@pytest.mark.asyncio
async def test_root_agent_lifecycle_uses_an_independent_chain() -> None:
    model = ScriptedModel(
        {
            AgentRole.REPORTER: [
                action("complete", summary="Report completed", data={"finding_count": 0})
            ]
        }
    )
    events = EventRecorder()
    registry = build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    dispatcher = AgentDispatcher(registry=registry, publisher=events.publish)
    task = AgentTask(run_id="run-root", flow_id="flow-root", objective="Write report")

    result = await dispatcher.dispatch_root(AgentRole.REPORTER, task)

    assert result.status == AgentStatus.COMPLETED
    assert result.summary == "Report completed"
    assert [item[0] for item in events.events] == [
        "agent.created",
        "agent.started",
        "decision.recorded",
        "agent.completed",
    ]
    instances = dispatcher.instances("run-root")
    assert len(instances) == 1
    chain = await dispatcher.chain_store.for_instance(instances[0].instance_id)
    assert chain.agent_role == AgentRole.REPORTER
    assert [message.role for message in chain.messages] == ["system", "user", "assistant"]


@pytest.mark.asyncio
async def test_pentagi_primary_specialist_reflector_chain_parity() -> None:
    model = ScriptedModel(
        {
            AgentRole.PRIMARY_AGENT: [
                action("delegate", role="coder", objective="Audit the Python source"),
                action("delegate", role="pentester", objective="Validate the reported weakness"),
                "The specialists have returned enough evidence.",
                action("complete", summary="Audit and validation completed"),
            ],
            AgentRole.CODER: [
                action("tool", tool_id="native:code_scan", arguments={"target": "."}),
                action(
                    "complete",
                    summary="Code scan completed",
                    evidence_ids=["evidence-code"],
                ),
            ],
            AgentRole.PENTESTER: [
                action(
                    "complete",
                    summary="Weakness validated",
                    evidence_ids=["evidence-validation"],
                    finding_ids=["finding-1"],
                )
            ],
            AgentRole.REFLECTOR: [
                "Return a complete action with the public evidence-backed summary."
            ],
        }
    )
    gateway = RecordingGateway()
    events = EventRecorder()
    registry = build_native_agent_registry(
        model=model,
        prompts=StaticPromptResolver(),
        max_iterations=10,
    )
    dispatcher = AgentDispatcher(
        registry=registry,
        publisher=events.publish,
        tool_gateway=gateway,
    )
    task = AgentTask(
        run_id="run-parity",
        flow_id="flow-parity",
        subtask_id="subtask-1",
        objective="Perform an authorized code audit and validate the result",
        expected_outputs=["evidence-backed finding"],
    )

    result = await dispatcher.dispatch_root(AgentRole.PRIMARY_AGENT, task)

    assert result.status == AgentStatus.COMPLETED
    assert result.summary == "Audit and validation completed"
    assert result.artifact_refs == ["artifact-code-report"]
    assert result.evidence_ids == ["evidence-code", "evidence-validation"]
    assert result.finding_ids == ["finding-1"]
    assert model.calls == [
        AgentRole.PRIMARY_AGENT,
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.PRIMARY_AGENT,
        AgentRole.PENTESTER,
        AgentRole.PRIMARY_AGENT,
        AgentRole.REFLECTOR,
        AgentRole.PRIMARY_AGENT,
    ]

    delegations = dispatcher.delegations("run-parity")
    assert [item.to_role for item in delegations] == [
        AgentRole.CODER,
        AgentRole.PENTESTER,
        AgentRole.REFLECTOR,
    ]
    assert all(item.status == AgentStatus.COMPLETED for item in delegations)
    assert all(item.to_agent_instance_id for item in delegations)

    messages = dispatcher.messages("run-parity")
    by_kind: dict[AgentMessageKind, int] = defaultdict(int)
    for message in messages:
        by_kind[message.kind] += 1
    assert by_kind == {
        AgentMessageKind.DELEGATION: 3,
        AgentMessageKind.RESPONSE: 3,
    }
    assert [item.sequence for item in messages] == [1, 2, 3, 4, 5, 6]

    instances = dispatcher.instances("run-parity")
    assert [item.role for item in instances] == [
        AgentRole.PRIMARY_AGENT,
        AgentRole.CODER,
        AgentRole.PENTESTER,
        AgentRole.REFLECTOR,
    ]
    primary = instances[0]
    assert all(item.parent_instance_id == primary.instance_id for item in instances[1:])
    chains = await dispatcher.chain_store.list_for_run("run-parity")
    assert len(chains) == 4
    assert len({item.chain_id for item in chains}) == 4
    assert {item.agent_instance_id for item in chains} == {
        item.instance_id for item in instances
    }

    assert len(gateway.invocations) == 1
    assert gateway.invocations[0].tool_id == "native:code_scan"
    assert gateway.invocations[0].subtask_id == "subtask-1"
    event_types = [item[0] for item in events.events]
    assert event_types.count("agent.delegated") == 3
    assert event_types.count("agent.message") == 6
    assert event_types[-1] == "agent.completed"


@pytest.mark.asyncio
async def test_pentagi_task_lifecycle_role_order_is_preserved() -> None:
    model = ScriptedModel(
        {
            AgentRole.GENERATOR: [
                action(
                    "complete",
                    summary="Subtasks generated",
                    data={"subtasks": ["Inspect source"]},
                )
            ],
            AgentRole.PRIMARY_AGENT: [
                action("delegate", role="coder", objective="Inspect source"),
                action("complete", summary="Subtask completed"),
            ],
            AgentRole.CODER: [
                action("complete", summary="Source inspected", evidence_ids=["evidence-1"])
            ],
            AgentRole.REFINER: [
                action("complete", summary="Remaining plan is valid")
            ],
            AgentRole.REPORTER: [
                action("complete", summary="Final report generated")
            ],
        }
    )
    registry = build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    dispatcher = AgentDispatcher(registry=registry)

    await dispatcher.dispatch_root(
        AgentRole.GENERATOR,
        AgentTask(run_id="run-task", flow_id="flow-task", objective="Generate plan"),
    )
    subtask_result = await dispatcher.dispatch_root(
        AgentRole.PRIMARY_AGENT,
        AgentTask(run_id="run-task", flow_id="flow-task", objective="Execute subtask"),
    )
    await dispatcher.dispatch_root(
        AgentRole.REFINER,
        AgentTask(run_id="run-task", flow_id="flow-task", objective="Refine remaining plan"),
    )
    report_result = await dispatcher.dispatch_root(
        AgentRole.REPORTER,
        AgentTask(run_id="run-task", flow_id="flow-task", objective="Report task results"),
    )

    assert model.calls == [
        AgentRole.GENERATOR,
        AgentRole.PRIMARY_AGENT,
        AgentRole.CODER,
        AgentRole.PRIMARY_AGENT,
        AgentRole.REFINER,
        AgentRole.REPORTER,
    ]
    assert subtask_result.evidence_ids == ["evidence-1"]
    assert report_result.summary == "Final report generated"
    assert [item.role for item in dispatcher.instances("run-task")] == [
        AgentRole.GENERATOR,
        AgentRole.PRIMARY_AGENT,
        AgentRole.CODER,
        AgentRole.REFINER,
        AgentRole.REPORTER,
    ]


@pytest.mark.asyncio
async def test_delegation_depth_failure_has_a_real_child_instance() -> None:
    model = ScriptedModel(
        {
            AgentRole.PRIMARY_AGENT: [
                action("delegate", role="coder", objective="First delegation"),
                action("complete", summary="Root handled depth failure"),
            ],
            AgentRole.CODER: [
                action("delegate", role="searcher", objective="Too-deep delegation"),
                action("complete", summary="Coder handled depth failure"),
            ],
        }
    )
    registry = build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    dispatcher = AgentDispatcher(registry=registry, max_delegation_depth=1)

    result = await dispatcher.dispatch_root(
        AgentRole.PRIMARY_AGENT,
        AgentTask(run_id="run-depth", flow_id="flow-depth", objective="Run nested task"),
    )

    assert result.status == AgentStatus.COMPLETED
    searcher = next(
        item for item in dispatcher.instances("run-depth") if item.role == AgentRole.SEARCHER
    )
    assert searcher.status == AgentStatus.FAILED
    assert dispatcher.result(searcher.instance_id).error_code == "AGENT_DELEGATION_DEPTH"
    assert AgentRole.SEARCHER not in model.calls
    nested = dispatcher.delegations("run-depth")[-1]
    assert nested.to_agent_instance_id == searcher.instance_id
    assert nested.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_invalid_actions_fail_after_bounded_reflection() -> None:
    model = ScriptedModel(
        {
            AgentRole.PRIMARY_AGENT: ["invalid one", "invalid two"],
            AgentRole.REFLECTOR: ["Correct it", "Correct it again"],
        }
    )
    registry = build_native_agent_registry(
        model=model,
        prompts=StaticPromptResolver(),
        max_iterations=5,
        max_reflections=1,
    )
    dispatcher = AgentDispatcher(registry=registry)
    task = AgentTask(run_id="run-invalid", flow_id="flow-invalid", objective="Do work")

    result = await dispatcher.dispatch_root(AgentRole.PRIMARY_AGENT, task)

    assert result.status == AgentStatus.FAILED
    assert result.error_code == "AGENT_ACTION_INVALID"
    assert [item.to_role for item in dispatcher.delegations()] == [AgentRole.REFLECTOR]
