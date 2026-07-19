"""Native multi-Agent abstractions and orchestrator implementations."""

from .chains import AgentMessageChain, InMemoryMessageChainStore, MessageChainStore
from .dispatcher import AgentDispatcher, EventPublisher
from .native import ModelNativeAgent, NativeAgent, PromptResolver, StaticPromptResolver, ToolGateway
from .registry import ROLE_DESCRIPTORS, NativeAgentRegistry, build_native_agent_registry
from .subgraph import NativeAgentSubgraph

__all__ = [
    "AgentDispatcher",
    "AgentMessageChain",
    "EventPublisher",
    "InMemoryMessageChainStore",
    "MessageChainStore",
    "ModelNativeAgent",
    "NativeAgent",
    "NativeAgentRegistry",
    "NativeAgentSubgraph",
    "PromptResolver",
    "ROLE_DESCRIPTORS",
    "StaticPromptResolver",
    "ToolGateway",
    "build_native_agent_registry",
]

