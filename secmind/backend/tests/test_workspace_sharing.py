from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agents.chains import AgentMessageChain
from agents.native import AgentRunContext
from app.database import create_native_repositories
from app.schemas.agents import AgentInstance, AgentResult, AgentRole, AgentStatus, AgentTask
from app.schemas.runtime import (
    AgentState,
    InputArtifact,
    RiskLevel,
    RuntimeToolContext,
    RuntimeToolResult,
    Scenario,
    TaskRequest,
    ToolManifest,
    ToolStatus,
)
from app.schemas.tools import ToolExecutionStatus, UnifiedToolInvocation
from app.services.collaboration import PersistedToolGateway, register_runtime_tools
from app.services.runtime import RuntimeEventHub
from app.services.workspace import RuntimeWorkspaceResolver
from ledger.runtime_store import RuntimeLedgerStore
from tools.mcp.gateway import UnifiedToolGateway
from tools.runtime import RuntimeTool, RuntimeToolRegistry


class EmptyMCPManager:
    def tool_definitions(self) -> list[Any]:
        return []

    async def call_tool(self, invocation: UnifiedToolInvocation) -> Any:
        raise AssertionError(f"Unexpected MCP invocation: {invocation.tool_id}")


class WorkspaceEchoTool(RuntimeTool):
    manifest = ToolManifest(
        name="workspace_echo",
        version="1",
        description="Return the server-bound workspace used by the tool.",
        scenarios=[Scenario.CODE_AUDIT],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk_level=RiskLevel.R0,
        permissions=["workspace:read"],
    )

    async def invoke(
        self,
        args: dict[str, Any],
        context: RuntimeToolContext,
    ) -> RuntimeToolResult:
        return RuntimeToolResult(
            status=ToolStatus.SUCCESS,
            summary="workspace resolved",
            data={"workspace": context.workspace, "target": args.get("target")},
        )


def save_workspace_state(
    ledger: RuntimeLedgerStore,
    run_root: Path,
    *,
    run_id: str,
    flow_id: str,
) -> Path:
    workspace = run_root / run_id / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "source.py"
    source.write_text("print('workspace')\n", encoding="utf-8")
    ledger.save_state(
        AgentState(
            run_id=run_id,
            flow_id=flow_id,
            task_id=f"task-{run_id}",
            task=TaskRequest(objective="audit workspace"),
            workspace=str(workspace.resolve()),
            input_artifacts=[
                InputArtifact(
                    original_name="source.py",
                    relative_path="source.py",
                    sha256="a" * 64,
                    size_bytes=source.stat().st_size,
                    media_type="text/x-python",
                )
            ],
        )
    )
    return workspace.resolve()


@pytest.mark.asyncio
async def test_agent_tool_calls_are_bound_to_their_run_workspace(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'workspace.db'}"
    repositories = create_native_repositories(database_url)
    ledger = RuntimeLedgerStore(database_url)
    run_root = tmp_path / "runs"
    flow = repositories.flows.ensure_flow("flow-workspace", title="Workspace test")
    workspaces = {
        run_id: save_workspace_state(ledger, run_root, run_id=run_id, flow_id=flow.id)
        for run_id in ("run-a", "run-b")
    }
    for run_id in workspaces:
        repositories.agents.create_instance(
            AgentInstance(
                instance_id=f"agent-{run_id}",
                run_id=run_id,
                flow_id=flow.id,
                role=AgentRole.CODER,
            )
        )

    resolver = RuntimeWorkspaceResolver(ledger=ledger, run_root=run_root)
    registry = RuntimeToolRegistry()
    registry.register(WorkspaceEchoTool())
    gateway = UnifiedToolGateway(EmptyMCPManager())  # type: ignore[arg-type]
    register_runtime_tools(gateway, registry, workspace_resolver=resolver)
    persisted = PersistedToolGateway(
        gateway=gateway,
        repositories=repositories,
        ledger=ledger,
        event_hub=RuntimeEventHub(),
        workspace_resolver=resolver,
    )

    for run_id, workspace in workspaces.items():
        result = await persisted.invoke(
            UnifiedToolInvocation(
                run_id=run_id,
                flow_id=flow.id,
                agent_instance_id=f"agent-{run_id}",
                tool_id="native:workspace_echo",
                arguments={"target": "."},
                metadata={
                    "scope": {
                        "workspace": str(workspaces["run-b"]),
                        "allowed_paths": [str(workspaces["run-b"])],
                    }
                },
            )
        )
        assert result.status == ToolExecutionStatus.COMPLETED
        assert result.data["workspace"] == str(workspace)

    escaped = await persisted.invoke(
        UnifiedToolInvocation(
            run_id="run-a",
            flow_id=flow.id,
            agent_instance_id="agent-run-a",
            tool_id="native:workspace_echo",
            arguments={"target": "../../run-b/workspace"},
        )
    )
    assert escaped.error_code == "scope_violation"

    started = next(item for item in ledger.events("run-a") if item.event_type == "tool.started")
    scope = started.payload["metadata"]["scope"]
    assert scope == {
        "workspace": str(workspaces["run-a"]),
        "allowed_paths": [str(workspaces["run-a"])],
    }


@pytest.mark.asyncio
async def test_delegated_agent_cannot_drop_parent_workspace_refs() -> None:
    captured: list[AgentTask] = []

    async def delegate(role: AgentRole, task: AgentTask) -> AgentResult:
        del role
        captured.append(task)
        return AgentResult(
            agent_instance_id="child-agent",
            task_id=task.task_id,
            status=AgentStatus.COMPLETED,
        )

    instance = AgentInstance(
        instance_id="root-agent",
        run_id="run-shared",
        flow_id="flow-shared",
        role=AgentRole.ASSISTANT,
    )
    task = AgentTask(
        run_id=instance.run_id,
        flow_id=instance.flow_id,
        objective="coordinate audit",
        context_refs=[
            "workspace://run-shared/",
            "workspace://run-shared/manifest",
        ],
    )
    context = AgentRunContext(
        instance=instance,
        task=task,
        chain=AgentMessageChain(
            run_id=instance.run_id,
            flow_id=instance.flow_id,
            agent_instance_id=instance.instance_id,
            agent_role=instance.role,
        ),
        delegate_callback=delegate,
        tool_callback=None,  # type: ignore[arg-type]
        message_callback=None,  # type: ignore[arg-type]
        wait_message_callback=None,  # type: ignore[arg-type]
        stop_requested_callback=lambda: False,
        runtime_event_callback=None,  # type: ignore[arg-type]
    )

    await context.delegate(
        AgentRole.CODER,
        objective="inspect one file",
        context_refs=["workspace://run-shared/source.py"],
    )

    assert captured[0].run_id == instance.run_id
    assert captured[0].flow_id == instance.flow_id
    assert captured[0].context_refs == [
        "workspace://run-shared/",
        "workspace://run-shared/manifest",
        "workspace://run-shared/source.py",
    ]
