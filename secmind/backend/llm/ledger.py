from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.runtime import EventContext
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse

TRACE_PARAMETER_KEYS = frozenset(
    {
        "stage",
        "model_profile",
        "agent_instance_id",
        "subtask_id",
        "iteration",
        "prompt_key",
        "prompt_version_id",
    }
)


class LedgerLLMProvider(LLMProvider):
    """Record model input/output around another provider without changing its API."""

    def __init__(self, provider: LLMProvider, ledger: RuntimeLedgerStore) -> None:
        self.provider = provider
        self.ledger = ledger
        self.name = provider.name

    def metadata(self) -> dict[str, Any]:
        metadata = self.provider.metadata().copy()
        metadata["ledger_tracing"] = True
        return metadata

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        run_id = kwargs.pop("run_id", None)
        flow_id = kwargs.pop("flow_id", None)
        task_id = kwargs.pop("task_id", None)
        trace_parameters = {
            key: kwargs.pop(key) for key in sorted(TRACE_PARAMETER_KEYS) if key in kwargs
        }
        context = EventContext(
            flow_id=flow_id,
            task_id=task_id,
            agent_instance_id=trace_parameters.get("agent_instance_id"),
        )
        trace_id = str(uuid4())
        if run_id is not None:
            self.ledger.append(
                run_id,
                event_type="llm.request",
                actor="llm_provider",
                payload={
                    "trace_id": trace_id,
                    "provider": self.provider.name,
                    "messages": [message.model_dump(mode="json") for message in messages],
                    "parameters": kwargs,
                    "trace_parameters": trace_parameters,
                },
                context=context,
            )

        try:
            response = await self.provider.complete(messages, **kwargs)
        except Exception as error:
            if run_id is not None:
                diagnostics = getattr(error, "diagnostics", None)
                self.ledger.append(
                    run_id,
                    event_type="llm.error",
                    actor="llm_provider",
                    payload={
                        "trace_id": trace_id,
                        "provider": self.provider.name,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "diagnostics": diagnostics if isinstance(diagnostics, dict) else None,
                    },
                    context=context,
                )
            raise

        if run_id is not None:
            self.ledger.append(
                run_id,
                event_type="llm.response",
                actor="llm_provider",
                payload={
                    "trace_id": trace_id,
                    "provider": response.provider,
                    "model": response.model,
                    "content": response.content,
                    "tool_calls": [
                        item.model_dump(mode="json") for item in response.tool_calls
                    ],
                    "finish_reason": response.finish_reason,
                    "usage": response.usage.model_dump(mode="json"),
                    "empty_content_reason": response.empty_content_reason,
                    "raw": response.raw,
                },
                context=context,
            )
        return response
