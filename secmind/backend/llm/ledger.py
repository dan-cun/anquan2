from __future__ import annotations

from typing import Any
from uuid import uuid4

from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse


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
                },
            )

        try:
            response = await self.provider.complete(messages, **kwargs)
        except Exception as error:
            if run_id is not None:
                self.ledger.append(
                    run_id,
                    event_type="llm.error",
                    actor="llm_provider",
                    payload={
                        "trace_id": trace_id,
                        "provider": self.provider.name,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
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
                    "raw": response.raw,
                },
            )
        return response
