from __future__ import annotations

from dataclasses import dataclass

from agents.guardrail import Guardrail
from agents.runtime_orchestrator import RuntimeOrchestrator
from app.core.config import Settings
from app.services.flows import FlowStore
from app.services.runtime import RuntimeEventHub, RuntimeRunService
from knowledge.store import InMemoryKnowledgeStore
from ledger.jsonl_store import JsonlLedgerStore
from ledger.runtime_store import RuntimeLedgerStore
from llm.manager import LLMProviderManager
from sandbox.base import DisabledSandbox
from tools.bandit_tool import default_runtime_registry
from tools.registry import ToolRegistry
from tools.runtime import RuntimeToolBroker


@dataclass(slots=True)
class AppServices:
    flows: FlowStore
    ledger: JsonlLedgerStore
    runtime_ledger: RuntimeLedgerStore
    runtime_events: RuntimeEventHub
    runtime: RuntimeRunService
    orchestrator: RuntimeOrchestrator
    tool_registry: ToolRegistry
    llm_provider: LLMProviderManager
    knowledge: InMemoryKnowledgeStore
    sandbox: DisabledSandbox

    async def startup(self) -> None:
        await self.runtime.recover_incomplete()

    async def shutdown(self) -> None:
        await self.runtime.shutdown()


def build_services(settings: Settings) -> AppServices:
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
    runtime_ledger = RuntimeLedgerStore(settings.resolved_runtime_database_url)
    runtime_events = RuntimeEventHub()
    llm_provider = LLMProviderManager(settings=settings, ledger=runtime_ledger)
    runtime = RuntimeRunService(
        settings=settings,
        ledger=runtime_ledger,
        broker=RuntimeToolBroker(runtime_tool_registry, Guardrail()),
        event_hub=runtime_events,
        llm_provider=llm_provider,
    )
    knowledge = InMemoryKnowledgeStore()
    sandbox = DisabledSandbox()
    orchestrator = RuntimeOrchestrator(runtime=runtime, flow_ledger=ledger)
    return AppServices(
        flows=flows,
        ledger=ledger,
        runtime_ledger=runtime_ledger,
        runtime_events=runtime_events,
        runtime=runtime,
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        llm_provider=llm_provider,
        knowledge=knowledge,
        sandbox=sandbox,
    )
