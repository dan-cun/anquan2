from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any, TypedDict

import ormsgpack
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.actions import AgentActionError, AgentActionType, parse_agent_action
from agents.dispatcher import AgentDispatcher
from agents.native import StaticPromptResolver
from agents.registry import ROLE_DESCRIPTORS, build_native_agent_registry
from agents.subgraph import AgentGraphState
from app.schemas.agents import AgentMessageKind, AgentRole, AgentStatus, AgentTask
from app.schemas.runtime import EventContext
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from llm.base import EmptyContentReason, LLMMessage, LLMProvider, LLMResponse


class ParentGraphState(TypedDict, total=False):
    objective: str
    result: dict[str, Any]


def action(action_type: str, **values: Any) -> str:
    return json.dumps({"action": action_type, **values})


class ScriptedModel(LLMProvider):
    name = "scripted"

    def __init__(self, scripts: dict[AgentRole, list[str | LLMResponse]]) -> None:
        self.scripts = {role: deque(items) for role, items in scripts.items()}
        self.calls: list[AgentRole] = []
        self.message_snapshots: list[list[LLMMessage]] = []
        self.request_kwargs: list[dict[str, Any]] = []

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        role = AgentRole(str(kwargs["stage"]).removeprefix("agent."))
        self.calls.append(role)
        self.message_snapshots.append(messages)
        self.request_kwargs.append(kwargs.copy())
        if not self.scripts[role]:
            raise AssertionError(f"No scripted response remains for {role.value}")
        scripted = self.scripts[role].popleft()
        if isinstance(scripted, LLMResponse):
            return scripted
        return LLMResponse(
            content=scripted,
            model=f"model-{kwargs['model_profile']}",
            provider=self.name,
        )


class RecordingGateway:
    def __init__(self) -> None:
        self.invocations: list[UnifiedToolInvocation] = []

    def definitions(self) -> list[UnifiedToolDefinition]:
        return [
            UnifiedToolDefinition(
                tool_id="native:code_scan",
                name="code_scan",
                description="Inspect source code",
                origin=ToolOrigin.NATIVE,
                input_schema={
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                },
                output_schema={"type": "object"},
            )
        ]

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


class DynamicCatalogGateway:
    def __init__(self) -> None:
        self.invocations: list[UnifiedToolInvocation] = []

    def definitions(self) -> list[UnifiedToolDefinition]:
        phase = len(self.invocations) + 1
        return [
            UnifiedToolDefinition(
                tool_id="native:dynamic",
                name="dynamic",
                description="A dynamically refreshed test tool",
                origin=ToolOrigin.NATIVE,
                input_schema={
                    "type": "object",
                    "properties": {"phase": {"const": phase}},
                    "required": ["phase"],
                },
                output_schema={
                    "type": "object",
                    "properties": {"observed_phase": {"type": "integer"}},
                },
                annotations={"allowed_roles": ["assistant"]},
            )
        ]

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        self.invocations.append(invocation)
        return UnifiedToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            data={"observed_phase": invocation.arguments["phase"]},
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
        "```json\n" + action("delegate", role="coder", objective="Create a scanner") + "\n```"
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


def test_native_agent_subgraph_checkpoint_state_is_msgpack_serializable() -> None:
    assert set(AgentGraphState.__annotations__) == {"context_id", "result"}
    state: AgentGraphState = {
        "context_id": "agent-1",
        "result": {
            "agent_instance_id": "agent-1",
            "task_id": "task-1",
            "status": "completed",
            "summary": "done",
        },
    }

    assert ormsgpack.unpackb(ormsgpack.packb(state)) == state


@pytest.mark.asyncio
async def test_parent_checkpoint_never_serializes_native_agent_runtime_context() -> None:
    model = ScriptedModel(
        {AgentRole.REPORTER: [action("complete", summary="Checkpoint-safe report completed")]}
    )
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    )

    async def execute_agent(state: ParentGraphState) -> ParentGraphState:
        result = await dispatcher.dispatch_root(
            AgentRole.REPORTER,
            AgentTask(
                run_id="run-checkpoint",
                flow_id="flow-checkpoint",
                objective=state["objective"],
            ),
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(ParentGraphState)
    builder.add_node("execute_agent", execute_agent)
    builder.add_edge(START, "execute_agent")
    builder.add_edge("execute_agent", END)
    graph = builder.compile(checkpointer=MemorySaver())

    state = await graph.ainvoke(
        {"objective": "Generate a report"},
        {"configurable": {"thread_id": "checkpoint-native-agent"}},
    )

    assert state["result"]["status"] == AgentStatus.COMPLETED.value
    assert state["result"]["summary"] == "Checkpoint-safe report completed"


@pytest.mark.asyncio
async def test_role_filtered_tool_catalog_is_refreshed_before_every_model_call() -> None:
    model = ScriptedModel(
        {
            AgentRole.ASSISTANT: [
                action("tool", tool_id="native:dynamic", arguments={"phase": 1}),
                action("complete", summary="Dynamic tool completed"),
            ]
        }
    )
    gateway = DynamicCatalogGateway()
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(model=model, prompts=StaticPromptResolver()),
        tool_gateway=gateway,
    )

    result = await dispatcher.dispatch_root(
        AgentRole.ASSISTANT,
        AgentTask(run_id="run-catalog", flow_id="flow-catalog", objective="Use the tool"),
    )

    assert result.status == AgentStatus.COMPLETED
    catalogs = [
        next(
            message
            for message in snapshot
            if message.metadata.get("context_kind") == "runtime_tool_catalog"
        )
        for snapshot in model.message_snapshots
    ]
    assert len(catalogs) == 2
    assert '"const":1' in catalogs[0].content
    assert '"const":2' in catalogs[1].content
    assert '"output_schema"' in catalogs[0].content
    assert catalogs[0].metadata["catalog_sha256"] != catalogs[1].metadata["catalog_sha256"]


@pytest.mark.asyncio
async def test_role_without_tool_capability_cannot_invoke_known_tool() -> None:
    model = ScriptedModel(
        {
            AgentRole.GENERATOR: [
                action("tool", tool_id="native:dynamic", arguments={"phase": 1}),
                action("complete", summary="Denied tool was not executed"),
            ]
        }
    )
    gateway = DynamicCatalogGateway()
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(model=model, prompts=StaticPromptResolver()),
        tool_gateway=gateway,
    )

    result = await dispatcher.dispatch_root(
        AgentRole.GENERATOR,
        AgentTask(run_id="run-denied", flow_id="flow-denied", objective="Generate a plan"),
    )

    assert result.status == AgentStatus.COMPLETED
    assert gateway.invocations == []
    second_request = model.message_snapshots[1]
    observation = next(
        message
        for message in second_request
        if message.metadata.get("context_kind") == "observation"
    )
    assert observation.role == "user"
    assert json.loads(observation.content)["observation_type"] == "agent_observation"
    assert "TOOL_NOT_ALLOWED_FOR_ROLE" in observation.content
    catalog = next(
        message
        for message in model.message_snapshots[0]
        if message.metadata.get("context_kind") == "runtime_tool_catalog"
    )
    assert '"tools":[]' in catalog.content


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
                "not valid action envelope",
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
            AgentRole.TOOLCALL_FIXER: [
                action("complete", summary="Audit and validation completed")
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
        AgentRole.TOOLCALL_FIXER,
    ]

    delegations = dispatcher.delegations("run-parity")
    assert [item.to_role for item in delegations] == [
        AgentRole.CODER,
        AgentRole.PENTESTER,
    ]
    assert all(item.status == AgentStatus.COMPLETED for item in delegations)
    assert all(item.to_agent_instance_id for item in delegations)

    messages = dispatcher.messages("run-parity")
    by_kind: dict[AgentMessageKind, int] = defaultdict(int)
    for message in messages:
        by_kind[message.kind] += 1
    assert by_kind == {
        AgentMessageKind.DELEGATION: 2,
        AgentMessageKind.RESPONSE: 2,
    }
    assert [item.sequence for item in messages] == [1, 2, 3, 4]

    instances = dispatcher.instances("run-parity")
    assert [item.role for item in instances] == [
        AgentRole.PRIMARY_AGENT,
        AgentRole.CODER,
        AgentRole.PENTESTER,
    ]
    primary = instances[0]
    assert all(item.parent_instance_id == primary.instance_id for item in instances[1:])
    chains = await dispatcher.chain_store.list_for_run("run-parity")
    assert len(chains) == 3
    assert len({item.chain_id for item in chains}) == 3
    assert {item.agent_instance_id for item in chains} == {item.instance_id for item in instances}
    primary_chain = next(item for item in chains if item.agent_role == AgentRole.PRIMARY_AGENT)
    delegated_observations = [
        message
        for message in primary_chain.messages
        if message.metadata.get("observation_source") == "agent"
    ]
    assert len(delegated_observations) == 2
    assert all(message.role == "user" for message in delegated_observations)
    assert all(message.role != "tool" for message in primary_chain.messages)
    observation_payloads = [json.loads(message.content) for message in delegated_observations]
    assert observation_payloads[0]["evidence_ids"] == ["evidence-code"]
    assert observation_payloads[1]["evidence_ids"] == ["evidence-validation"]
    assert all(
        item["final_report"]["report_type"] == "agent_final_report"
        for item in observation_payloads
    )

    assert len(gateway.invocations) == 1
    assert gateway.invocations[0].tool_id == "native:code_scan"
    assert gateway.invocations[0].subtask_id == "subtask-1"
    event_types = [item[0] for item in events.events]
    assert event_types.count("agent.delegated") == 2
    assert event_types.count("agent.message") == 4
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
            AgentRole.REFINER: [action("complete", summary="Remaining plan is valid")],
            AgentRole.REPORTER: [action("complete", summary="Final report generated")],
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
            AgentRole.PRIMARY_AGENT: ["invalid one"],
            AgentRole.TOOLCALL_FIXER: ["still invalid"],
        }
    )
    registry = build_native_agent_registry(
        model=model,
        prompts=StaticPromptResolver(),
        max_iterations=5,
        max_reflections=1,
    )
    events = EventRecorder()
    dispatcher = AgentDispatcher(registry=registry, publisher=events.publish)
    task = AgentTask(run_id="run-invalid", flow_id="flow-invalid", objective="Do work")

    result = await dispatcher.dispatch_root(AgentRole.PRIMARY_AGENT, task)

    assert result.status == AgentStatus.FAILED
    assert result.error_code == "AGENT_ACTION_REPAIR_FAILED"
    assert model.calls == [AgentRole.PRIMARY_AGENT, AgentRole.TOOLCALL_FIXER]
    assert dispatcher.delegations() == []
    chain = await dispatcher.chain_store.for_instance(dispatcher.instances()[0].instance_id)
    repair = [
        message
        for message in chain.messages
        if message.metadata.get("observation_source") == "policy"
    ]
    assert len(repair) == 1
    assert "AGENT_ACTION_REPAIR_FAILED" in repair[0].content
    assert "invalid one" not in repair[0].content
    invalid_event = next(item for item in events.events if item[0] == "agent.action_invalid")
    assert set(invalid_event[1]) == {
        "run_id",
        "flow_id",
        "agent_instance_id",
        "task_id",
        "response_sha256",
        "diagnostic",
        "repair_attempts_used",
    }
    assert "invalid one" not in json.dumps(invalid_event[1])


@pytest.mark.asyncio
async def test_reasoning_only_action_retries_without_thinking_before_fixer() -> None:
    model = ScriptedModel(
        {
            AgentRole.PRIMARY_AGENT: [
                LLMResponse(
                    content=" ",
                    model="scripted-model",
                    provider="scripted",
                    empty_content_reason=EmptyContentReason.REASONING_ONLY,
                ),
                action("complete", summary="Recovered after disabling thinking"),
            ]
        }
    )
    registry = build_native_agent_registry(
        model=model,
        prompts=StaticPromptResolver(),
        max_iterations=3,
    )
    dispatcher = AgentDispatcher(registry=registry)

    result = await dispatcher.dispatch_root(
        AgentRole.PRIMARY_AGENT,
        AgentTask(run_id="run-reasoning-only", flow_id="flow-reasoning-only", objective="Do work"),
    )

    assert result.status == AgentStatus.COMPLETED, (
        result.error_code,
        result.error_message,
        model.calls,
        model.request_kwargs,
    )
    assert model.calls == [AgentRole.PRIMARY_AGENT, AgentRole.PRIMARY_AGENT]
    assert "thinking_enabled" not in model.request_kwargs[0]
    assert model.request_kwargs[1]["thinking_enabled"] is False


def workspace_metadata() -> dict[str, Any]:
    return {
        "workspace_evidence_required": True,
        "workspace_context": {
            "version": "native-agent-workspace-v1",
            "manifest": {
                "file_count": 1,
                "files": [
                    {
                        "artifact_id": "artifact-source",
                        "path": "src/source.py",
                        "sha256": "a" * 64,
                    }
                ],
            },
            "chunks": [
                {
                    "artifact_id": "artifact-source",
                    "path": "src/source.py",
                    "start_line": 1,
                    "end_line": 2,
                    "content": "def safe():\n    return True\n",
                }
            ],
            "allowed_artifact_refs": ["artifact-source"],
        },
    }


@pytest.mark.asyncio
async def test_delegated_agent_inherits_bounded_workspace_evidence() -> None:
    model = ScriptedModel(
        {
            AgentRole.ASSISTANT: [
                action("delegate", role="coder", objective="Inspect the supplied source"),
                action("complete", summary="Audit completed"),
            ],
            AgentRole.CODER: [
                action(
                    "complete",
                    summary="Source inspected; no unsupported claim was made",
                    artifact_refs=["artifact-source"],
                )
            ],
        }
    )
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    )

    result = await dispatcher.dispatch_root(
        AgentRole.ASSISTANT,
        AgentTask(
            run_id="run-workspace-evidence",
            flow_id="flow-workspace-evidence",
            objective="Audit the supplied repository",
            context_refs=[
                "workspace://run-workspace-evidence/",
                "workspace://run-workspace-evidence/manifest",
                "workspace://run-workspace-evidence/src/source.py",
            ],
            metadata=workspace_metadata(),
        ),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.artifact_refs == ["artifact-source"]
    coder_snapshot = model.message_snapshots[1]
    workspace_message = next(
        item
        for item in coder_snapshot
        if item.metadata.get("context_kind") == "workspace_evidence"
    )
    assert "def safe()" in workspace_message.content
    assert "artifact-source" in workspace_message.content
    coder_task = dispatcher.delegations("run-workspace-evidence")[0].task
    assert coder_task.metadata == workspace_metadata()
    assert len(coder_task.context_refs) == 3


@pytest.mark.asyncio
async def test_fabricated_completion_without_repository_evidence_is_rejected() -> None:
    model = ScriptedModel(
        {
            AgentRole.PENTESTER: [
                action(
                    "complete",
                    summary="Fabricated command injection in unrelated example code",
                    data={
                        "final_answer": "subprocess.call(user_input, shell=True)",
                        "reproduction_steps": ["Run the invented snippet"],
                    },
                ),
                action(
                    "complete",
                    summary="Still unsupported",
                    data={"final_answer": "invented vulnerability"},
                ),
            ]
        }
    )
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(
            model=model,
            prompts=StaticPromptResolver(),
            max_iterations=2,
        )
    )

    result = await dispatcher.dispatch_root(
        AgentRole.PENTESTER,
        AgentTask(
            run_id="run-fabricated",
            flow_id="flow-fabricated",
            objective="Validate a repository vulnerability",
            metadata=workspace_metadata(),
        ),
    )

    assert result.status == AgentStatus.FAILED
    assert result.error_code == "AGENT_ITERATION_LIMIT"
    assert result.artifact_refs == []
    chain = await dispatcher.chain_store.for_instance(
        dispatcher.instances("run-fabricated")[0].instance_id
    )
    support_observations = [
        item
        for item in chain.messages
        if item.metadata.get("observation_source") == "policy"
        and "Completion rejected" in item.content
    ]
    assert len(support_observations) == 2


@pytest.mark.asyncio
async def test_evidence_backed_workspace_completion_is_accepted() -> None:
    model = ScriptedModel(
        {
            AgentRole.PENTESTER: [
                action(
                    "complete",
                    summary="Repository source was inspected",
                    data={"reproduction_steps": ["Inspect src/source.py lines 1-2"]},
                    artifact_refs=["artifact-source"],
                )
            ]
        }
    )
    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(model=model, prompts=StaticPromptResolver())
    )

    result = await dispatcher.dispatch_root(
        AgentRole.PENTESTER,
        AgentTask(
            run_id="run-supported",
            flow_id="flow-supported",
            objective="Validate a repository finding",
            metadata=workspace_metadata(),
        ),
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.artifact_refs == ["artifact-source"]
