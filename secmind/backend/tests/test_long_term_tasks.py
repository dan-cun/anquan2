from __future__ import annotations

from app.database import create_native_repositories
from app.schemas.long_term import NoteKind, TodoStatus
from app.schemas.tools import ToolExecutionStatus, UnifiedToolInvocation
from app.services.long_term import LongTermTaskService, register_long_term_tools
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import Base, RuntimeLedgerStore
from tools.mcp.gateway import UnifiedToolGateway


class EmptyMCPManager:
    def tool_definitions(self):
        return []


async def test_long_term_state_round_trip_and_context_compression(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'long-term.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    flow = repositories.flows.create_flow(title="长期审计")
    ledger = RuntimeLedgerStore(database_url, auto_create_schema=False)
    service = LongTermTaskService(
        repositories.long_term,
        repositories.results,
        ledger,
        RuntimeEventHub(),
    )

    skill = await service.register_skill(
        skill_id="web.audit",
        name="Web 审计",
        content="只依据已授权范围执行；所有结论引用 Evidence。",
        tags=["web", "audit"],
    )
    load = await service.load_skill(
        skill_id=skill.skill_id,
        run_id="run-1",
        flow_id=flow.id,
        agent_instance_id="agent-1",
        reason="需要 Web 审计流程",
    )
    todo = await service.create_todo(
        run_id="run-1",
        flow_id=flow.id,
        title="验证登录端点",
        agent_instance_id="agent-1",
    )
    completed = await service.update_todo(todo.todo_id, status=TodoStatus.COMPLETED)
    note = await service.record_note(
        run_id="run-1",
        flow_id=flow.id,
        kind=NoteKind.FACT,
        content="目标返回 HTTP 200。",
        evidence_ids=["evidence-1"],
    )
    ledger.append(
        "run-1",
        "tool.completed",
        {"tool_id": "native:http", "endpoint": "https://authorized.test/login"},
    )

    snapshot = await service.compress_context(run_id="run-1", flow_id=flow.id)
    second_snapshot = await service.compress_context(run_id="run-1", flow_id=flow.id)
    context = service.agent_context("run-1", "agent-1")

    assert skill.checksum
    assert load.skill_id == skill.skill_id
    assert completed.completed_at is not None
    assert note.evidence_ids == ["evidence-1"]
    assert snapshot.structured.endpoints[0]["value"].endswith("/login")
    assert snapshot.source_to_sequence > snapshot.source_from_sequence
    assert second_snapshot.source_to_sequence > snapshot.source_to_sequence
    assert second_snapshot.structured.tools == []
    assert context["loaded_skills"][0]["content"].startswith("只依据")
    assert context["context_snapshot"]["snapshot_id"] == second_snapshot.snapshot_id
    assert ledger.verify("run-1") is True


async def test_agent_native_long_term_tools_are_model_visible_and_failure_wrapped(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'tools.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    flow = repositories.flows.create_flow(title="Agent tools")
    ledger = RuntimeLedgerStore(database_url, auto_create_schema=False)
    service = LongTermTaskService(
        repositories.long_term,
        repositories.results,
        ledger,
        RuntimeEventHub(),
    )
    gateway = UnifiedToolGateway(EmptyMCPManager())  # type: ignore[arg-type]
    register_long_term_tools(gateway, service)

    tool_ids = {item.tool_id for item in gateway.definitions()}
    assert {
        "native:skill.list",
        "native:skill.load",
        "native:todo.list",
        "native:todo.create",
        "native:todo.update",
        "native:notes.list",
        "native:notes.record",
        "native:context.compress",
    } <= tool_ids

    result = await gateway.invoke(
        UnifiedToolInvocation(
            run_id="run-tools",
            flow_id=flow.id,
            agent_instance_id="agent-tools",
            tool_id="native:todo.create",
            arguments={"title": "保留执行状态"},
        )
    )
    failure = await gateway.invoke(
        UnifiedToolInvocation(
            run_id="run-tools",
            flow_id=flow.id,
            agent_instance_id="agent-tools",
            tool_id="native:skill.load",
            arguments={"skill_id": "missing"},
        )
    )

    assert result.status == ToolExecutionStatus.COMPLETED
    assert service.list_todos("run-tools")[0].title == "保留执行状态"
    assert failure.status == ToolExecutionStatus.FAILED
    assert failure.error_code == "KeyError"
