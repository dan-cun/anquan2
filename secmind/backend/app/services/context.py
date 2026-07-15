from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from agents.guardrail import Guardrail
from agents.runtime_orchestrator import RuntimeOrchestrator
from app.core.config import Settings
from app.services.flows import FlowStore
from app.services.runtime import RuntimeEventHub, RuntimeRunService
from knowledge.service import QdrantKnowledgeService
from knowledge.store import InMemoryKnowledgeStore
from ledger.checkpoints import CheckpointerFactory
from ledger.jsonl_store import JsonlLedgerStore
from ledger.projections import ProjectionReducer
from ledger.runtime_store import RuntimeLedgerStore
from llm.manager import LLMProviderManager
from sandbox.base import DisabledSandbox
from tools.bandit_tool import default_runtime_registry
from tools.registry import ToolRegistry
from tools.runtime import RuntimeToolBroker

KnowledgeBackend = InMemoryKnowledgeStore | QdrantKnowledgeService


@dataclass(slots=True)
class AppServices:
    settings: Settings
    flows: FlowStore
    ledger: JsonlLedgerStore
    runtime_ledger: RuntimeLedgerStore
    runtime_events: RuntimeEventHub
    runtime: RuntimeRunService
    orchestrator: RuntimeOrchestrator
    tool_registry: ToolRegistry
    llm_provider: LLMProviderManager
    knowledge: KnowledgeBackend
    knowledge_backend: str
    checkpointer: Any
    projection: ProjectionReducer | None
    projection_listener: Callable[[Any], None] | None
    sandbox: DisabledSandbox

    async def startup(self) -> None:
        if self.projection is not None:
            if self.settings.projection_rebuild_on_start:
                self.projection.rebuild()
            else:
                for run_id in self.runtime_ledger.run_ids():
                    self.projection.project_run(run_id)
        await self.runtime.recover_incomplete()

    async def shutdown(self) -> None:
        await self.runtime.shutdown()
        if self.projection_listener is not None:
            self.runtime_ledger.remove_event_listener(self.projection_listener)
        close_knowledge = getattr(self.knowledge, "close", None)
        if callable(close_knowledge):
            close_knowledge()
        self.runtime_ledger.engine.dispose()


def build_services(settings: Settings, *, checkpointer: Any | None = None) -> AppServices:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_ledger_dir.mkdir(parents=True, exist_ok=True)
    settings.prepare_runtime_directories()

    flows = FlowStore()
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
    runtime = RuntimeRunService(
        settings=settings,
        ledger=runtime_ledger,
        broker=RuntimeToolBroker(runtime_tool_registry, Guardrail()),
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
    return AppServices(
        settings=settings,
        flows=flows,
        ledger=ledger,
        runtime_ledger=runtime_ledger,
        runtime_events=runtime_events,
        runtime=runtime,
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        llm_provider=llm_provider,
        knowledge=knowledge,
        knowledge_backend=knowledge_backend,
        checkpointer=checkpointer,
        projection=projection,
        projection_listener=projection_listener,
        sandbox=sandbox,
    )


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
