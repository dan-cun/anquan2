from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graphql.context import GraphQLContext
from app.graphql.ports import GraphQLBackend
from app.graphql.router import create_graphql_router
from app.graphql.schema import graphql_schema
from app.graphql.types import (
    AgentRole,
    Approval,
    CapabilityKind,
    CreateFlowInput,
    Flow,
    MCPServer,
    MCPServerStatus,
    RegisterMCPServerInput,
    RuntimeEvent,
    Subtask,
    Task,
)


class FakeGraphQLPort:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.flow_rows = [
            Flow(
                id="flow-1",
                title="Security audit",
                status="running",
                created_at=now,
                updated_at=now,
            ),
            Flow(
                id="flow-2",
                title="Incident review",
                status="created",
                created_at=now,
                updated_at=now,
            ),
        ]
        self.task_rows = {
            "flow-1": [
                Task(
                    id="task-1",
                    flow_id="flow-1",
                    title="Audit source",
                    objective="audit",
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            ],
            "flow-2": [],
        }
        self.subtask_rows = {
            "task-1": [
                Subtask(
                    id="subtask-1",
                    task_id="task-1",
                    title="Run scanner",
                    description="Run the scanner",
                    status="running",
                    agent_role=AgentRole.PENTESTER,
                    created_at=now,
                    updated_at=now,
                )
            ]
        }
        self.task_batch_calls = 0
        self.subtask_batch_calls = 0
        self.last_approval: tuple[str, str, bool, str | None] | None = None
        self.last_registered_server: RegisterMCPServerInput | None = None

    async def list_flows(self):
        return [row for row in self.flow_rows]

    async def get_flow(self, flow_id: str):
        return next((row for row in self.flow_rows if str(row.id) == flow_id), None)

    async def list_tasks(self, flow_id: str):
        return self.task_rows.get(flow_id, [])

    async def list_tasks_batch(self, flow_ids: list[str]):
        self.task_batch_calls += 1
        return {flow_id: self.task_rows.get(flow_id, []) for flow_id in flow_ids}

    async def list_subtasks(self, task_id: str):
        return self.subtask_rows.get(task_id, [])

    async def list_subtasks_batch(self, task_ids: list[str]):
        self.subtask_batch_calls += 1
        return {task_id: self.subtask_rows.get(task_id, []) for task_id in task_ids}

    async def create_flow(self, input: CreateFlowInput):
        now = datetime.now(UTC)
        flow = Flow(
            id="flow-created",
            title=input.title or input.input[:20],
            status="created",
            created_at=now,
            updated_at=now,
        )
        self.flow_rows.append(flow)
        return flow

    async def resolve_approval(
        self,
        run_id: str,
        request_id: str,
        approved: bool,
        reason: str | None,
    ):
        self.last_approval = (run_id, request_id, approved, reason)
        now = datetime.now(UTC)
        return Approval(
            request_id=request_id,
            run_id=run_id,
            step_id="step-1",
            status="resolved",
            reason=reason or "",
            decision="approve" if approved else "deny",
            actor="operator",
            requested_at=now,
            resolved_at=now,
        )

    async def register_server(self, input: RegisterMCPServerInput):
        self.last_registered_server = input
        return MCPServer(
            server_id=input.server_id,
            name=input.name,
            transport=input.transport,
            enabled=input.enabled,
            status=MCPServerStatus.CONNECTED,
            metadata=input.metadata or {},
            capabilities=[],
        )

    async def list_capabilities(self, server_id: str | None, kind: CapabilityKind | None):
        return []

    def subscribe(self, topic: str, **filters: Any) -> AsyncIterator[Any]:
        async def iterator() -> AsyncIterator[Any]:
            assert topic == "runtime.event"
            assert filters == {"run_id": "run-1", "after_sequence": 4}
            yield RuntimeEvent(
                event_id="event-5",
                run_id="run-1",
                sequence=5,
                event_type="agent.started",
                actor="runtime",
                payload={"role": "pentester"},
                timestamp=datetime.now(UTC),
                prev_hash="a" * 64,
                hash="b" * 64,
            )

        return iterator()


def backend(port: FakeGraphQLPort) -> GraphQLBackend:
    return GraphQLBackend(
        flows=port,
        agents=port,
        tools=port,
        mcp=port,
        prompts=port,
        audit=port,
        analytics=port,
        events=port,
    )


async def test_query_hydrates_hierarchy_with_request_dataloaders() -> None:
    port = FakeGraphQLPort()
    result = await graphql_schema.execute(
        """
        query {
          flows {
            id
            title
            tasks { id subtasks { id agentRole } }
          }
        }
        """,
        context_value=GraphQLContext.create(backend(port)),
    )
    assert result.errors is None
    assert result.data == {
        "flows": [
            {
                "id": "flow-1",
                "title": "Security audit",
                "tasks": [
                    {
                        "id": "task-1",
                        "subtasks": [{"id": "subtask-1", "agentRole": "PENTESTER"}],
                    }
                ],
            },
            {"id": "flow-2", "title": "Incident review", "tasks": []},
        ]
    }
    assert port.task_batch_calls == 1
    assert port.subtask_batch_calls == 1


async def test_mutations_delegate_to_domain_ports() -> None:
    port = FakeGraphQLPort()
    context = GraphQLContext.create(backend(port))
    result = await graphql_schema.execute(
        """
        mutation {
          createFlow(input: {title: "New flow", input: "audit"}) { id title status }
          approveAction(runId: "run-1", requestId: "approval-1", reason: "ok") {
            requestId decision
          }
          registerMCPServer(input: {
            serverId: "local"
            name: "Local MCP"
            transport: STDIO
            command: "python"
          }) { serverId status }
        }
        """,
        context_value=context,
    )
    assert result.errors is None
    assert result.data == {
        "createFlow": {"id": "flow-created", "title": "New flow", "status": "created"},
        "approveAction": {"requestId": "approval-1", "decision": "approve"},
        "registerMCPServer": {"serverId": "local", "status": "CONNECTED"},
    }
    assert port.last_approval == ("run-1", "approval-1", True, "ok")
    assert port.last_registered_server is not None
    assert port.last_registered_server.command == "python"


async def test_subscription_delegates_replay_cursor_to_event_port() -> None:
    port = FakeGraphQLPort()
    stream = await graphql_schema.subscribe(
        """
        subscription {
          runtimeEventAdded(runId: "run-1", afterSequence: 4) {
            runId sequence eventType payload
          }
        }
        """,
        context_value=GraphQLContext.create(backend(port)),
    )
    result = await anext(stream)
    assert result.errors is None
    assert result.data == {
        "runtimeEventAdded": {
            "runId": "run-1",
            "sequence": 5,
            "eventType": "agent.started",
            "payload": {"role": "pentester"},
        }
    }
    await stream.aclose()


def test_router_constructor_supports_fastapi_http_context() -> None:
    port = FakeGraphQLPort()
    app = FastAPI()
    app.include_router(create_graphql_router(lambda _connection: backend(port)), prefix="/graphql")
    with TestClient(app) as client:
        response = client.post(
            "/graphql",
            json={"query": 'query { flow(flowId: "flow-1") { id title } }'},
        )
    assert response.status_code == 200
    assert response.json() == {"data": {"flow": {"id": "flow-1", "title": "Security audit"}}}


async def test_not_found_and_invalid_cursor_are_graphql_errors() -> None:
    port = FakeGraphQLPort()
    context = GraphQLContext.create(backend(port))
    missing = await graphql_schema.execute(
        'query { flow(flowId: "missing") { id } }',
        context_value=context,
    )
    assert missing.data is None
    assert missing.errors[0].extensions == {"code": "NOT_FOUND"}

    invalid = await graphql_schema.execute(
        'query { agentMessages(flowId: "flow-1", afterSequence: -1) { messageId } }',
        context_value=context,
    )
    assert invalid.data is None
    assert invalid.errors[0].message == "afterSequence must not be negative"
