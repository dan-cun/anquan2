from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.database import create_native_repositories
from app.database.models import PromptVersionRow
from app.schemas.agents import (
    AgentDelegation,
    AgentInstance,
    AgentMessage,
    AgentMessageKind,
    AgentRole,
    AgentStatus,
    AgentTask,
)
from app.schemas.flow import FlowStatus
from app.schemas.mcp import MCPCapability, MCPServerConfig, MCPTransport
from app.schemas.prompts import (
    PromptMessageRole,
    PromptTemplateRecord,
    PromptVersionRecord,
    PromptVersionStatus,
)
from app.schemas.tools import (
    CapabilityKind,
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from ledger.runtime_store import Base

NATIVE_TABLES = {
    "flows",
    "tasks",
    "subtasks",
    "agent_instances",
    "agent_delegations",
    "agent_messages",
    "message_chains",
    "message_entries",
    "prompts",
    "prompt_versions",
    "mcp_servers",
    "mcp_capabilities",
    "tool_calls",
    "artifacts",
    "evidence",
    "findings",
    "reports",
    "approvals",
    "llm_calls",
    "llm_usage",
}


@pytest.fixture
def repositories(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'native.db'}"
    result = create_native_repositories(database_url)
    Base.metadata.create_all(result.engine)
    yield result
    result.engine.dispose()


def test_native_models_cover_frozen_business_tables(repositories) -> None:
    assert NATIVE_TABLES.issubset(set(inspect(repositories.engine).get_table_names()))


def test_alembic_upgrades_and_downgrades_native_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SECMIND_DATABASE_URL", raising=False)
    monkeypatch.delenv("SECMIND_RUNTIME_DATABASE_URL", raising=False)
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    migrated = create_native_repositories(database_url)
    tables = set(inspect(migrated.engine).get_table_names())
    assert NATIVE_TABLES.issubset(tables)
    assert "runtime_ledger_events" in tables
    command.check(config)

    command.downgrade(config, "20260715_0001")
    tables = set(inspect(migrated.engine).get_table_names())
    assert not NATIVE_TABLES.intersection(tables)
    assert "runtime_ledger_events" in tables
    migrated.engine.dispose()


def test_flow_repository_persists_and_soft_deletes(repositories, tmp_path) -> None:
    flow = repositories.flows.create_flow(initial_input="Inspect the authorized application")
    repositories.flows.update_status(flow.id, FlowStatus.running)

    second = create_native_repositories(f"sqlite:///{tmp_path / 'native.db'}")
    restored = second.flows.get_flow(flow.id)
    assert restored is not None
    assert restored.status == FlowStatus.running
    assert restored.title == "Inspect the authorized application"

    deleted = second.flows.delete_flow(flow.id)
    assert deleted.id == flow.id
    assert second.flows.get_flow(flow.id) is None
    assert second.flows.list_flows() == []
    second.engine.dispose()


def test_task_and_subtask_hierarchy_is_durable(repositories) -> None:
    flow = repositories.flows.create_flow(title="Native flow")
    task = repositories.tasks.create_task(
        flow_id=flow.id,
        title="Audit task",
        objective="Audit the Python service",
    )
    later = repositories.tasks.create_subtask(
        task_id=task.id,
        title="Verify",
        description="Verify evidence",
        position=2,
        agent_role=AgentRole.REFLECTOR.value,
        dependencies=["scan"],
    )
    first = repositories.tasks.create_subtask(
        subtask_id="scan",
        task_id=task.id,
        title="Scan",
        description="Run security tools",
        position=1,
        agent_role=AgentRole.PENTESTER.value,
    )

    assert [item.id for item in repositories.tasks.list_subtasks(task.id)] == [
        first.id,
        later.id,
    ]
    repositories.tasks.update_subtask(later.id, status="completed", result={"ok": True})
    assert repositories.tasks.list_subtasks(task.id)[1].result_json == {"ok": True}


def test_agent_delegation_messages_and_independent_chain(repositories) -> None:
    flow = repositories.flows.create_flow(title="Agents")
    task = repositories.tasks.create_task(
        flow_id=flow.id,
        title="Agent task",
        objective="Delegate work",
    )
    primary = AgentInstance(
        instance_id="agent-primary",
        run_id="run-1",
        flow_id=flow.id,
        role=AgentRole.PRIMARY_AGENT,
        status=AgentStatus.RUNNING,
        task_id=task.id,
        model_profile="planner",
    )
    repositories.agents.create_instance(primary)
    delegation = AgentDelegation(
        delegation_id="delegation-1",
        run_id="run-1",
        flow_id=flow.id,
        from_agent_instance_id=primary.instance_id,
        to_role=AgentRole.CODER,
        task=AgentTask(
            task_id=task.id,
            run_id="run-1",
            flow_id=flow.id,
            objective="Review the source code",
        ),
    )
    repositories.agents.create_delegation(delegation)
    coder = AgentInstance(
        instance_id="agent-coder",
        run_id="run-1",
        flow_id=flow.id,
        role=AgentRole.CODER,
        status=AgentStatus.RUNNING,
        task_id=task.id,
        parent_instance_id=primary.instance_id,
    )
    repositories.agents.create_instance(coder)
    repositories.prompts.upsert_template(
        PromptTemplateRecord(
            prompt_key="coder",
            name="Coder",
            category="agent",
            message_role=PromptMessageRole.SYSTEM,
        )
    )
    prompt_version = repositories.prompts.create_version(
        PromptVersionRecord(
            prompt_key="coder",
            version=1,
            content="Review code",
            checksum="prompt-version-checksum",
            status=PromptVersionStatus.ACTIVE,
        )
    )
    updated_coder = repositories.agents.update_instance_status(
        coder.instance_id,
        AgentStatus.COMPLETED,
        prompt_version_id=prompt_version.version_id,
        metadata={"chain_id": "chain-coder"},
    )
    assert updated_coder.prompt_version_id == prompt_version.version_id
    assert updated_coder.metadata == {"chain_id": "chain-coder"}
    completed = repositories.agents.complete_delegation(
        delegation.delegation_id,
        status=AgentStatus.COMPLETED,
        result_summary="Review completed",
        to_agent_instance_id=coder.instance_id,
    )
    assert completed.to_agent_instance_id == coder.instance_id

    message = AgentMessage(
        run_id="run-1",
        flow_id=flow.id,
        from_agent_instance_id=coder.instance_id,
        to_agent_instance_id=primary.instance_id,
        kind=AgentMessageKind.RESPONSE,
        summary="Evidence-backed review completed",
        sequence=3,
    )
    repositories.agents.append_message(message)
    assert repositories.agents.list_messages("run-1", after_sequence=2) == [message]

    chain = repositories.agents.create_chain(
        chain_id="chain-coder",
        run_id="run-1",
        flow_id=flow.id,
        task_id=task.id,
        agent_instance_id=coder.instance_id,
        agent_role=AgentRole.CODER,
        model_provider="qwen",
        model="qwen-plus",
    )
    first_entry = repositories.agents.append_chain_entry(
        chain_id=chain.chain_id,
        role="user",
        content="Review the service",
    )
    second_entry = repositories.agents.append_chain_entry(
        chain_id=chain.chain_id,
        role="assistant",
        content="Review completed",
    )
    assert (first_entry.sequence, second_entry.sequence) == (1, 2)


def test_prompt_repository_versions_without_overwrite(repositories) -> None:
    template = PromptTemplateRecord(
        prompt_key="coder",
        name="Coder",
        category="agent",
        message_role=PromptMessageRole.SYSTEM,
        agent_role=AgentRole.CODER,
        variables=["CurrentTime"],
    )
    repositories.prompts.upsert_template(template)
    first = PromptVersionRecord(
        version_id="prompt-v1",
        prompt_key="coder",
        version=1,
        content="Time: {{ CurrentTime }}",
        variables=["CurrentTime"],
        checksum="sha256:v1",
        status=PromptVersionStatus.ACTIVE,
        activated_at=datetime.now(UTC),
    )
    second = PromptVersionRecord(
        version_id="prompt-v2",
        prompt_key="coder",
        version=2,
        content="Current time: {{ CurrentTime }}",
        variables=["CurrentTime"],
        checksum="sha256:v2",
    )
    repositories.prompts.create_version(first)
    repositories.prompts.create_version(second)
    repositories.prompts.activate_version("coder", second.version_id)

    active = repositories.prompts.get_active_version("coder")
    assert active is not None and active.version_id == second.version_id
    with repositories.sessions() as session:
        assert session.get(PromptVersionRow, first.version_id).status == "archived"
    with pytest.raises(ValueError, match="already exists"):
        repositories.prompts.create_version(second)


def test_mcp_capabilities_and_tool_calls_share_native_lifecycle(repositories) -> None:
    flow = repositories.flows.create_flow(title="MCP")
    agent = AgentInstance(
        instance_id="agent-searcher",
        run_id="run-mcp",
        flow_id=flow.id,
        role=AgentRole.SEARCHER,
    )
    repositories.agents.create_instance(agent)
    server = MCPServerConfig(
        server_id="research",
        name="Research",
        transport=MCPTransport.STREAMABLE_HTTP,
        url="https://mcp.example.test",
        header_refs={"Authorization": "SECMIND_MCP_TOKEN"},
    )
    repositories.mcp.upsert_server(server)
    capability = MCPCapability(
        capability_id="research:search",
        server_id=server.server_id,
        kind=CapabilityKind.TOOL,
        name="search",
        input_schema={"type": "object"},
    )
    assert repositories.mcp.replace_capabilities(server.server_id, [capability]) == [capability]

    invocation = UnifiedToolInvocation(
        invocation_id="call-1",
        run_id="run-mcp",
        flow_id=flow.id,
        agent_instance_id=agent.instance_id,
        tool_id="mcp:research:search",
        arguments={"query": "CVE-2026"},
    )
    repositories.tool_calls.create_invocation(
        invocation,
        origin=ToolOrigin.MCP,
        server_id=server.server_id,
    )
    repositories.tool_calls.mark_running(invocation.invocation_id)
    completed = repositories.tool_calls.complete(
        UnifiedToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            text="Search completed",
            evidence_ids=["evidence-1"],
            duration_ms=42,
        )
    )
    assert completed.origin == ToolOrigin.MCP.value
    assert completed.status == ToolExecutionStatus.COMPLETED.value
    assert completed.evidence_ids_json == ["evidence-1"]


def test_results_survive_flow_soft_delete(repositories) -> None:
    flow = repositories.flows.create_flow(title="Results")
    artifact = repositories.results.record_artifact(
        artifact_id="artifact-1",
        run_id="run-results",
        flow_id=flow.id,
        name="report.json",
        media_type="application/json",
        uri="artifact://report.json",
        sha256="a" * 64,
    )
    evidence = repositories.results.record_evidence(
        evidence_id="evidence-1",
        run_id="run-results",
        source="tool",
        summary="Captured output",
        artifact_ref=artifact.artifact_id,
    )
    repositories.results.record_finding(
        finding_id="finding-1",
        run_id="run-results",
        rule_id="B101",
        severity="HIGH",
        confidence="HIGH",
        path="app.py",
        title="Unsafe call",
        description="Unsafe process invocation",
        evidence_ids=[evidence.evidence_id],
    )
    first = repositories.results.record_report(
        run_id="run-results",
        status="completed",
        executive_summary="One finding",
    )
    second = repositories.results.record_report(
        run_id="run-results",
        status="completed",
        executive_summary="Updated report",
    )
    repositories.flows.delete_flow(flow.id)

    assert (first.version, second.version) == (1, 2)
    assert repositories.results.latest_report("run-results").report_id == second.report_id
    assert [item.evidence_id for item in repositories.results.list_evidence("run-results")] == [
        evidence.evidence_id
    ]
    assert [item.finding_id for item in repositories.results.list_findings("run-results")] == [
        "finding-1"
    ]


def test_approval_and_llm_usage_lifecycles(repositories) -> None:
    flow = repositories.flows.create_flow(title="Approval and usage")
    approval = repositories.approvals.create(
        request_id="approval-1",
        run_id="run-accounting",
        step_id="step-1",
        tool_name="mcp:security:scan",
        reason="Operator confirmation requested",
        request={"target": "authorized.example"},
    )
    resolved = repositories.approvals.resolve(
        approval.request_id,
        decision="approve",
        actor="operator",
        reason="Authorized target confirmed",
        response={"approved": True},
    )
    assert resolved.status == "resolved"
    approvals = repositories.approvals.list_for_run("run-accounting")
    assert [item.request_id for item in approvals] == [resolved.request_id]
    assert approvals[0].decision == "approve"
    with pytest.raises(ValueError, match="already resolved"):
        repositories.approvals.resolve(
            approval.request_id,
            decision="deny",
            actor="operator",
        )

    call = repositories.llm.start_call(
        call_id="llm-call-1",
        run_id="run-accounting",
        flow_id=flow.id,
        provider="deepseek",
        model="deepseek-chat",
        stage="plan",
        request_ref="ledger://run-accounting/1",
    )
    repositories.llm.complete_call(
        call.call_id,
        status="completed",
        response_ref="ledger://run-accounting/2",
        duration_ms=125,
    )
    usage = repositories.llm.record_usage(
        usage_id="usage-1",
        call_id=call.call_id,
        run_id="run-accounting",
        flow_id=flow.id,
        provider="deepseek",
        model="deepseek-chat",
        prompt_tokens=100,
        completion_tokens=40,
        cache_read_tokens=10,
        total_tokens=140,
        duration_ms=125,
    )
    assert usage.total_tokens == 140
    usages = repositories.llm.list_usage("run-accounting")
    assert [item.usage_id for item in usages] == [usage.usage_id]
    assert usages[0].total_tokens == 140
    assert usages[0].cache_read_tokens == 10
