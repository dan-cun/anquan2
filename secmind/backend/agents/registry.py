from __future__ import annotations

from collections.abc import Callable

from app.schemas.agents import AgentDescriptor, AgentRole
from llm.base import LLMProvider

from .loop_guard import LoopGuardConfig
from .native import ModelNativeAgent, NativeAgent, PromptResolver
from .runtime_dependencies import AgentRuntimeDependencies
from .subgraph import NativeAgentSubgraph

AgentBuilder = Callable[[AgentDescriptor], NativeAgent]


ROLE_DESCRIPTORS: tuple[AgentDescriptor, ...] = (
    AgentDescriptor(
        role=AgentRole.PRIMARY_AGENT,
        display_name="Primary Agent",
        description="Coordinates specialist Agents until the assigned subtask is complete.",
        prompt_key="primary_agent",
        model_profile="planner",
        capabilities=["agent:delegate", "tool:invoke"],
    ),
    AgentDescriptor(
        role=AgentRole.ASSISTANT,
        display_name="Assistant",
        description="Handles interactive requests and delegates or invokes tools directly.",
        prompt_key="assistant",
        model_profile="planner",
        capabilities=["agent:delegate", "tool:invoke", "flow:control"],
    ),
    AgentDescriptor(
        role=AgentRole.GENERATOR,
        display_name="Generator",
        description="Decomposes a Task into ordered Subtasks.",
        prompt_key="generator",
        model_profile="planner",
        capabilities=["plan:create", "agent:delegate"],
    ),
    AgentDescriptor(
        role=AgentRole.REFINER,
        display_name="Refiner",
        description="Revises remaining Subtasks after execution results.",
        prompt_key="refiner",
        model_profile="planner",
        capabilities=["plan:revise", "agent:delegate"],
    ),
    AgentDescriptor(
        role=AgentRole.ADVISER,
        display_name="Adviser",
        description="Provides technical recommendations, planning, and execution monitoring.",
        prompt_key="adviser",
        capabilities=["agent:delegate", "tool:invoke"],
    ),
    AgentDescriptor(
        role=AgentRole.REFLECTOR,
        display_name="Reflector",
        description="Corrects Agent responses that violate the structured action protocol.",
        prompt_key="reflector",
        model_profile="fallback",
        capabilities=["response:repair"],
    ),
    AgentDescriptor(
        role=AgentRole.SEARCHER,
        display_name="Searcher",
        description="Retrieves intelligence from native and MCP sources.",
        prompt_key="searcher",
        capabilities=["tool:invoke", "knowledge:search"],
    ),
    AgentDescriptor(
        role=AgentRole.ENRICHER,
        display_name="Enricher",
        description="Builds additional context from search and memory results.",
        prompt_key="enricher",
        capabilities=["agent:delegate", "tool:invoke", "context:enrich"],
    ),
    AgentDescriptor(
        role=AgentRole.CODER,
        display_name="Coder",
        description="Writes and validates code, scripts, and security utilities.",
        prompt_key="coder",
        capabilities=["agent:delegate", "tool:invoke", "code:write"],
    ),
    AgentDescriptor(
        role=AgentRole.INSTALLER,
        display_name="Installer",
        description="Installs and configures tools in the controlled environment.",
        prompt_key="installer",
        capabilities=["agent:delegate", "tool:invoke", "environment:maintain"],
    ),
    AgentDescriptor(
        role=AgentRole.PENTESTER,
        display_name="Pentester",
        description="Performs authorized security tests and vulnerability validation.",
        prompt_key="pentester",
        capabilities=["agent:delegate", "tool:invoke", "security:test"],
    ),
    AgentDescriptor(
        role=AgentRole.MEMORIST,
        display_name="Memorist",
        description="Retrieves and stores reusable execution knowledge.",
        prompt_key="memorist",
        capabilities=["tool:invoke", "knowledge:search", "knowledge:store"],
    ),
    AgentDescriptor(
        role=AgentRole.REPORTER,
        display_name="Reporter",
        description="Produces evidence-backed Task reports.",
        prompt_key="reporter",
        model_profile="planner",
        capabilities=["report:write", "agent:delegate"],
    ),
    AgentDescriptor(
        role=AgentRole.SUMMARIZER,
        display_name="Summarizer",
        description="Compresses long message chains while retaining public facts.",
        prompt_key="summarizer",
        model_profile="fallback",
        capabilities=["context:summarize"],
    ),
    AgentDescriptor(
        role=AgentRole.TOOLCALL_FIXER,
        display_name="Tool Call Fixer",
        description="Repairs malformed tool names and arguments.",
        prompt_key="toolcall_fixer",
        model_profile="fallback",
        capabilities=["tool:repair"],
    ),
)


class NativeAgentRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[AgentRole, AgentDescriptor] = {}
        self._builders: dict[AgentRole, AgentBuilder] = {}
        self._subgraphs: dict[AgentRole, NativeAgentSubgraph] = {}
        self.runtime_dependencies = AgentRuntimeDependencies()

    def register(self, descriptor: AgentDescriptor, builder: AgentBuilder) -> None:
        if descriptor.role in self._descriptors:
            raise ValueError(f"Duplicate Agent role: {descriptor.role.value}")
        self._descriptors[descriptor.role] = descriptor
        self._builders[descriptor.role] = builder

    def descriptor(self, role: AgentRole) -> AgentDescriptor:
        try:
            return self._descriptors[role]
        except KeyError as error:
            raise KeyError(f"Unknown Agent role: {role.value}") from error

    def descriptors(self) -> list[AgentDescriptor]:
        return list(self._descriptors.values())

    def create(self, role: AgentRole) -> NativeAgent:
        descriptor = self.descriptor(role)
        if not descriptor.enabled:
            raise ValueError(f"Agent role is disabled: {role.value}")
        return self._builders[role](descriptor)

    def subgraph(self, role: AgentRole) -> NativeAgentSubgraph:
        if role not in self._subgraphs:
            self._subgraphs[role] = NativeAgentSubgraph(
                self.create(role),
                self.runtime_dependencies,
            )
        return self._subgraphs[role]


def build_native_agent_registry(
    *,
    model: LLMProvider,
    prompts: PromptResolver,
    max_iterations: int = 24,
    max_reflections: int = 3,
    max_action_repair_attempts: int | None = 1,
    loop_guard_config: LoopGuardConfig | None = None,
) -> NativeAgentRegistry:
    registry = NativeAgentRegistry()

    def build(descriptor: AgentDescriptor) -> NativeAgent:
        return ModelNativeAgent(
            descriptor,
            model=model,
            prompts=prompts,
            max_iterations=max_iterations,
            max_reflections=max_reflections,
            max_action_repair_attempts=max_action_repair_attempts,
            loop_guard_config=loop_guard_config,
        )

    for descriptor in ROLE_DESCRIPTORS:
        registry.register(descriptor, build)
    return registry
