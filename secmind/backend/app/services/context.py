from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from agents.chains import MessageChainStore
from agents.dispatcher import AgentDispatcher
from agents.guardrail import Guardrail
from agents.persistence import PersistentMessageChainStore
from agents.registry import NativeAgentRegistry, build_native_agent_registry
from agents.runtime_orchestrator import RuntimeOrchestrator
from agents.verifier import IndependentVerifier, VerificationRequest, register_verifier_tool
from app.core.config import Settings
from app.database import NativeRepositories, create_native_repositories
from app.database.repositories import FlowRepository
from app.schemas.agents import AgentRole
from app.schemas.runtime import EventContext
from app.services.collaboration import (
    NativeCollaborationService,
    NativeDemoLLMProvider,
    PersistedToolGateway,
    register_runtime_tools,
)
from app.services.event_stream import RuntimeEventStream
from app.services.execution import UnifiedExecutionService
from app.services.long_term import LongTermTaskService, register_long_term_tools
from app.services.runtime import RuntimeEventHub, RuntimeRunService
from app.services.workspace import RuntimeWorkspaceResolver
from knowledge.service import QdrantKnowledgeService
from knowledge.store import InMemoryKnowledgeStore
from ledger.checkpoints import CheckpointerFactory
from ledger.jsonl_store import JsonlLedgerStore
from ledger.projections import ProjectionReducer
from ledger.runtime_store import RuntimeLedgerStore
from llm.manager import LLMProviderManager
from prompts import NativePromptRegistry
from sandbox.base import DisabledSandbox
from tools.bandit_tool import default_runtime_registry
from tools.mcp import MCPManager, UnifiedToolGateway, load_mcp_server_configs
from tools.registry import ToolRegistry
from tools.runtime import RuntimeToolBroker

KnowledgeBackend = InMemoryKnowledgeStore | QdrantKnowledgeService


@dataclass(slots=True)
class AppServices:
    settings: Settings
    repositories: NativeRepositories
    flows: FlowRepository
    ledger: JsonlLedgerStore
    runtime_ledger: RuntimeLedgerStore
    runtime_events: RuntimeEventHub
    runtime_event_stream: RuntimeEventStream
    runtime: RuntimeRunService
    workspace_resolver: RuntimeWorkspaceResolver
    execution: UnifiedExecutionService
    orchestrator: RuntimeOrchestrator
    collaboration: NativeCollaborationService
    agent_registry: NativeAgentRegistry
    agent_dispatcher: AgentDispatcher
    prompt_registry: NativePromptRegistry
    long_term: LongTermTaskService
    verifier: IndependentVerifier
    mcp_manager: MCPManager
    tool_gateway: PersistedToolGateway
    tool_registry: ToolRegistry
    llm_provider: LLMProviderManager
    knowledge: KnowledgeBackend
    knowledge_backend: str
    checkpointer: Any
    projection: ProjectionReducer | None
    projection_listener: Callable[[Any], None] | None
    sandbox: DisabledSandbox
    graphql_adapter: Any
    graphql_events: Any

    async def startup(self) -> None:
        if self.projection is not None:
            if self.settings.projection_rebuild_on_start:
                self.projection.rebuild()
            else:
                for run_id in self.runtime_ledger.run_ids():
                    self.projection.project_run(run_id)
        await self.mcp_manager.startup()
        await self.runtime.recover_incomplete()

    async def shutdown(self) -> None:
        await self.mcp_manager.shutdown()
        await self.runtime.shutdown()
        if self.projection_listener is not None:
            self.runtime_ledger.remove_event_listener(self.projection_listener)
        close_knowledge = getattr(self.knowledge, "close", None)
        if callable(close_knowledge):
            close_knowledge()
        self.runtime_ledger.engine.dispose()
        self.repositories.engine.dispose()


def build_services(settings: Settings, *, checkpointer: Any | None = None) -> AppServices:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_ledger_dir.mkdir(parents=True, exist_ok=True)
    settings.prepare_runtime_directories()

    repositories = create_native_repositories(
        settings.resolved_database_url,
        echo=settings.database_echo,
    )
    flows = repositories.flows
    ledger = JsonlLedgerStore(
        ledger_dir=settings.resolved_ledger_dir,
        snapshot_interval=settings.ledger_snapshot_interval,
    )
    tool_registry = ToolRegistry()
    runtime_tool_registry = default_runtime_registry()
    runtime_ledger = RuntimeLedgerStore(settings.resolved_database_url)
    runtime_events = RuntimeEventHub()
    runtime_event_stream = RuntimeEventStream(
        runtime_ledger,
        runtime_events,
        batch_size=settings.event_stream_batch_size,
        poll_interval_seconds=settings.event_stream_poll_interval_seconds,
    )
    llm_provider = LLMProviderManager(settings=settings, ledger=runtime_ledger)
    if settings.qdrant_enabled:
        knowledge: KnowledgeBackend = QdrantKnowledgeService.from_settings(settings)
        runtime_knowledge = knowledge
        knowledge_backend = "qdrant"
    else:
        knowledge = InMemoryKnowledgeStore()
        runtime_knowledge = None
        knowledge_backend = "memory"
    runtime_broker = RuntimeToolBroker(runtime_tool_registry, Guardrail())
    runtime = RuntimeRunService(
        settings=settings,
        ledger=runtime_ledger,
        broker=runtime_broker,
        event_hub=runtime_events,
        llm_provider=llm_provider,
        checkpointer=checkpointer,
        checkpoint_namespace=settings.checkpoint_namespace,
        knowledge_service=runtime_knowledge,
    )
    workspace_resolver = RuntimeWorkspaceResolver(
        ledger=runtime_ledger,
        run_root=settings.resolved_runtime_run_root,
    )
    projection = (
        ProjectionReducer(runtime_ledger, batch_size=settings.projection_batch_size)
        if settings.projection_enabled
        else None
    )
    projection_listener = None
    if projection is not None:

        def project_event(event: Any) -> None:
            projection.project_run(event.run_id)

        projection_listener = project_event
        runtime_ledger.add_event_listener(projection_listener)
    sandbox = DisabledSandbox()
    configured_servers = {
        item.config.server_id: item.config for item in repositories.mcp.list_servers()
    }
    for config in load_mcp_server_configs(settings.mcp_config_file):
        configured_servers[config.server_id] = config
        repositories.mcp.upsert_server(config)

    mcp_manager: MCPManager | None = None

    async def publish_mcp_event(event_type: str, payload: dict[str, Any]) -> None:
        event = runtime_ledger.append("system-mcp", event_type, payload, actor="mcp_manager")
        await runtime_events.publish(event.model_dump(mode="json"))
        if mcp_manager is None:
            return
        server_id = str(payload.get("server_id") or "")
        snapshot = next(
            (item for item in mcp_manager.snapshots() if item.config.server_id == server_id),
            None,
        )
        if snapshot is not None:
            repositories.mcp.upsert_server(
                snapshot.config,
                status=snapshot.status,
                protocol_version=snapshot.protocol_version,
                last_error=snapshot.error_message,
            )
            repositories.mcp.replace_capabilities(server_id, snapshot.capabilities)

    mcp_manager = MCPManager(
        list(configured_servers.values()),
        connect_timeout_seconds=settings.mcp_connect_timeout_seconds,
        call_timeout_seconds=settings.mcp_call_timeout_seconds,
        refresh_interval_seconds=settings.mcp_refresh_interval_seconds,
        publisher=publish_mcp_event,
    )
    unified_gateway = UnifiedToolGateway(
        mcp_manager,
        default_timeout_seconds=settings.mcp_call_timeout_seconds,
    )
    register_runtime_tools(
        unified_gateway,
        runtime_tool_registry,
        workspace_resolver=workspace_resolver,
    )
    long_term = LongTermTaskService(
        repositories.long_term,
        repositories.results,
        runtime_ledger,
        runtime_events,
    )
    register_long_term_tools(unified_gateway, long_term)
    tool_gateway = PersistedToolGateway(
        gateway=unified_gateway,
        repositories=repositories,
        ledger=runtime_ledger,
        event_hub=runtime_events,
        workspace_resolver=workspace_resolver,
    )

    def resolve_verification_evidence(
        run_id: str,
        finding_id: str,
        evidence_ids: list[str],
    ) -> set[str]:
        available = {item.evidence_id for item in repositories.results.list_evidence(run_id)}
        finding = next(
            (
                item
                for item in repositories.results.list_findings(run_id)
                if item.finding_id == finding_id
            ),
            None,
        )
        if finding is None:
            return set()
        return available.intersection(evidence_ids, finding.evidence_ids_json)

    async def publish_verification_event(
        event_type: str,
        request: VerificationRequest,
        payload: dict[str, Any],
    ) -> None:
        event = runtime_ledger.append(
            request.run_id,
            event_type,
            {
                "run_id": request.run_id,
                "flow_id": request.flow_id,
                "verifier_agent_instance_id": request.verifier_agent_instance_id,
                **payload,
            },
            actor="independent_verifier",
            context=EventContext(
                flow_id=request.flow_id,
                correlation_id=request.verification_id,
                agent_instance_id=request.verifier_agent_instance_id,
            ),
        )
        await runtime_events.publish(event.model_dump(mode="json"))

    verifier = IndependentVerifier(
        tool_gateway=tool_gateway,
        evidence_resolver=resolve_verification_evidence,
        publisher=publish_verification_event,
    )
    register_verifier_tool(unified_gateway, verifier)
    runtime.set_tool_catalog_provider(unified_gateway.definitions)
    prompt_registry = NativePromptRegistry(repositories.prompts)
    if settings.prompt_workbook_path is not None:
        prompt_registry.import_workbook(settings.prompt_workbook_path)
    else:
        prompt_registry.seed_catalog()
    native_model = (
        NativeDemoLLMProvider()
        if settings.runtime_demo_mode and not llm_provider.metadata().get("configured")
        else llm_provider
    )
    agent_registry = build_native_agent_registry(
        model=native_model,
        prompts=prompt_registry,
    )
    metadata = native_model.metadata()
    chain_store: MessageChainStore = PersistentMessageChainStore(
        repositories.agents,
        provider=str(metadata.get("provider") or metadata.get("name") or "unknown"),
        model=str(metadata.get("model") or getattr(native_model, "name", settings.llm_model)),
    )
    collaboration: NativeCollaborationService | None = None

    async def publish_agent_event(
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        context: EventContext | None = None,
    ) -> None:
        if collaboration is None:
            raise RuntimeError("Native collaboration service is not ready")
        await collaboration.publish_agent_event(event_type, payload, actor, context)

    agent_dispatcher = AgentDispatcher(
        registry=agent_registry,
        publisher=publish_agent_event,
        tool_gateway=tool_gateway,
        chain_store=chain_store,
        max_parallel=settings.agent_max_parallel,
        max_delegation_depth=settings.agent_max_delegation_depth,
        context_provider=long_term.agent_context,
    )
    collaboration = NativeCollaborationService(
        dispatcher=agent_dispatcher,
        repositories=repositories,
        ledger=runtime_ledger,
        event_hub=runtime_events,
    )
    execution = UnifiedExecutionService(runtime=runtime, repositories=repositories)

    async def run_native_collaboration(state: Any, review_round: int) -> dict[str, Any]:
        role = AgentRole.REFLECTOR if review_round == 2 else AgentRole.ASSISTANT
        workspace_refs = workspace_resolver.context_refs(state.run_id)
        _, result = await collaboration.submit(
            flow_id=state.flow_id or state.run_id,
            run_id=state.run_id,
            task_id=state.task_id,
            objective=state.task.objective,
            context_refs=workspace_refs,
            constraints=state.task.constraints,
            expected_outputs=state.task.expected_outputs,
            metadata={
                "review_round": review_round,
                "workspace_ref": workspace_refs[0],
                "allowed_tool_ids": (
                    state.capability_plan.allowed_tool_ids
                    if state.capability_plan is not None
                    else []
                ),
            },
            role=role,
        )
        return collaboration.collect_run_products(state.run_id, result)

    runtime.set_collaboration_runner(run_native_collaboration)

    def finalize_runtime_task(task_id: str, run_status: Any, report: dict[str, Any]) -> None:
        repositories.tasks.update_task(
            task_id,
            status=run_status.value,
            result=report,
        )
        run_id = str(report["run_id"])
        known_artifacts = {item.artifact_id for item in repositories.results.list_artifacts(run_id)}
        known_evidence = {item.evidence_id for item in repositories.results.list_evidence(run_id)}
        for item in report.get("evidence", []):
            evidence_id = str(item["evidence_id"])
            if evidence_id in known_evidence:
                continue
            artifact_ref = item.get("artifact_ref")
            repositories.results.record_evidence(
                evidence_id=evidence_id,
                run_id=run_id,
                source=str(item.get("source") or "runtime"),
                summary=str(item.get("summary") or ""),
                artifact_ref=artifact_ref if artifact_ref in known_artifacts else None,
                sha256=item.get("sha256"),
                metadata=dict(item.get("metadata") or {}),
            )
            known_evidence.add(evidence_id)
        known_findings = {item.finding_id for item in repositories.results.list_findings(run_id)}
        for item in report.get("findings", []):
            finding_id = str(item["finding_id"])
            if finding_id in known_findings:
                continue
            repositories.results.record_finding(
                finding_id=finding_id,
                run_id=run_id,
                rule_id=str(item.get("rule_id") or "UNKNOWN"),
                severity=str(item.get("severity") or "UNKNOWN"),
                confidence=str(item.get("confidence") or "UNKNOWN"),
                path=str(item.get("path") or ""),
                line=item.get("line"),
                title=str(item.get("title") or "Untitled finding"),
                description=str(item.get("description") or ""),
                remediation=item.get("remediation"),
                evidence_ids=list(item.get("evidence_ids") or []),
                raw=dict(item.get("raw") or {}),
            )
            known_findings.add(finding_id)
        repositories.results.record_report(
            run_id=run_id,
            status=run_status.value,
            executive_summary=str(report.get("executive_summary") or ""),
            findings=list(report.get("findings") or []),
            evidence=list(report.get("evidence") or []),
            limitations=list(report.get("limitations") or []),
        )

    runtime.set_task_finalizer(finalize_runtime_task)
    orchestrator = RuntimeOrchestrator(
        runtime=runtime,
        execution=execution,
        flow_ledger=ledger,
        event_stream=runtime_event_stream,
    )
    services = AppServices(
        settings=settings,
        repositories=repositories,
        flows=flows,
        ledger=ledger,
        runtime_ledger=runtime_ledger,
        runtime_events=runtime_events,
        runtime_event_stream=runtime_event_stream,
        runtime=runtime,
        workspace_resolver=workspace_resolver,
        execution=execution,
        orchestrator=orchestrator,
        collaboration=collaboration,
        agent_registry=agent_registry,
        agent_dispatcher=agent_dispatcher,
        prompt_registry=prompt_registry,
        long_term=long_term,
        verifier=verifier,
        mcp_manager=mcp_manager,
        tool_gateway=tool_gateway,
        tool_registry=tool_registry,
        llm_provider=llm_provider,
        knowledge=knowledge,
        knowledge_backend=knowledge_backend,
        checkpointer=checkpointer,
        projection=projection,
        projection_listener=projection_listener,
        sandbox=sandbox,
        graphql_adapter=None,
        graphql_events=None,
    )
    from app.graphql.adapters import NativeGraphQLAdapter, NativeGraphQLEventAdapter

    services.graphql_adapter = NativeGraphQLAdapter(services)
    services.graphql_events = NativeGraphQLEventAdapter(services)
    return services


@asynccontextmanager
async def open_services(settings: Settings) -> AsyncIterator[AppServices]:
    factory = CheckpointerFactory(
        backend=settings.checkpoint_backend,
        database_url=settings.resolved_checkpoint_database_url,
    )
    async with factory.open() as checkpointer:
        services = build_services(settings, checkpointer=checkpointer)
        try:
            await services.startup()
            yield services
        finally:
            await services.shutdown()
