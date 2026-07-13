from __future__ import annotations

from dataclasses import dataclass

from agents.mock_orchestrator import MockOrchestrator
from app.core.config import Settings
from app.services.flows import FlowStore
from knowledge.store import InMemoryKnowledgeStore
from ledger.jsonl_store import JsonlLedgerStore
from llm.base import LLMProvider
from llm.factory import build_llm_provider
from sandbox.base import DisabledSandbox
from tools.registry import ToolRegistry


@dataclass(slots=True)
class AppServices:
    flows: FlowStore
    ledger: JsonlLedgerStore
    orchestrator: MockOrchestrator
    tool_registry: ToolRegistry
    llm_provider: LLMProvider
    knowledge: InMemoryKnowledgeStore
    sandbox: DisabledSandbox


def build_services(settings: Settings) -> AppServices:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_ledger_dir.mkdir(parents=True, exist_ok=True)

    flows = FlowStore()
    ledger = JsonlLedgerStore(
        ledger_dir=settings.resolved_ledger_dir,
        snapshot_interval=settings.ledger_snapshot_interval,
    )
    tool_registry = ToolRegistry()
    llm_provider = build_llm_provider(settings)
    knowledge = InMemoryKnowledgeStore()
    sandbox = DisabledSandbox()
    orchestrator = MockOrchestrator(
        ledger=ledger,
        tool_registry=tool_registry,
        llm_provider=llm_provider,
        step_delay_seconds=settings.mock_step_delay_seconds,
    )
    return AppServices(
        flows=flows,
        ledger=ledger,
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        llm_provider=llm_provider,
        knowledge=knowledge,
        sandbox=sandbox,
    )
