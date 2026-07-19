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
from app.core.config import Settings
from app.database import NativeRepositories, create_native_repositories
from app.database.repositories import FlowRepository
from app.services.collaboration import (
    NativeCollaborationService,
    NativeDemoLLMProvider,
    PersistedToolGateway,
    register_runtime_tools,
)
from app.services.runtime import RuntimeEventHub, RuntimeRunService
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
    runtime: RuntimeRunService
    orchestrator: RuntimeOrchestrator
    collaboration: NativeCollaborationService
    agent_registry: NativeAgentRegistry
    agent_dispatcher: AgentDispatcher
    prompt_registry: NativePromptRegistry
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
    orchestrator = RuntimeOrchestrator(runtime=runtime, flow_ledger=ledger)

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
    unified_gateway = UnifiedToolGateway(mcp_manager)
    register_runtime_tools(
        unified_gateway,
        runtime_tool_registry,
        workspace=settings.resolved_runtime_input_root,
    )
    tool_gateway = PersistedToolGateway(
        gateway=unified_gateway,
        repositories=repositories,
        ledger=runtime_ledger,
        event_hub=runtime_events,
    )
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
    ) -> None:
        if collaboration is None:
            raise RuntimeError("Native collaboration service is not ready")
        await collaboration.publish_agent_event(event_type, payload, actor)

    agent_dispatcher = AgentDispatcher(
        registry=agent_registry,
        publisher=publish_agent_event,
        tool_gateway=tool_gateway,
        chain_store=chain_store,
        max_parallel=settings.agent_max_parallel,
        max_delegation_depth=settings.agent_max_delegation_depth,
    )
    collaboration = NativeCollaborationService(
        dispatcher=agent_dispatcher,
        repositories=repositories,
        ledger=runtime_ledger,
        event_hub=runtime_events,
    )
    services = AppServices(
        settings=settings,
        repositories=repositories,
        flows=flows,
        ledger=ledger,
        runtime_ledger=runtime_ledger,
        runtime_events=runtime_events,
        runtime=runtime,
        orchestrator=orchestrator,
        collaboration=collaboration,
        agent_registry=agent_registry,
        agent_dispatcher=agent_dispatcher,
        prompt_registry=prompt_registry,
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
