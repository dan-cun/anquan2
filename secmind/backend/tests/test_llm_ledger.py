import pytest

from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse
from llm.ledger import LedgerLLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    async def complete(self, messages, **kwargs):
        return LLMResponse(
            content="safe answer",
            model="fake-model",
            provider=self.name,
            raw={"request_token": "Bearer secret-token"},
        )


class FailingProvider(LLMProvider):
    name = "failing"

    async def complete(self, messages, **kwargs):
        raise RuntimeError("upstream failed with Bearer secret-token")


@pytest.mark.asyncio
async def test_llm_request_and_response_are_recorded_and_redacted(tmp_path):
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'ledger.db'}")
    provider = LedgerLLMProvider(FakeProvider(), ledger)

    response = await provider.complete(
        [LLMMessage(role="user", content="inspect this")],
        run_id="run-1",
        api_key="secret-key",
    )

    assert response.content == "safe answer"
    events = ledger.events("run-1")
    assert [event.event_type for event in events] == ["llm.request", "llm.response"]
    assert events[0].payload["parameters"]["api_key"] == "[REDACTED]"
    assert events[1].payload["raw"]["request_token"] == "Bearer [REDACTED]"
    assert ledger.verify("run-1") is True


@pytest.mark.asyncio
async def test_llm_error_is_recorded_before_exception(tmp_path):
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'ledger.db'}")
    provider = LedgerLLMProvider(FailingProvider(), ledger)

    with pytest.raises(RuntimeError, match="upstream failed"):
        await provider.complete(
            [LLMMessage(role="user", content="inspect this")],
            run_id="run-2",
        )

    events = ledger.events("run-2")
    assert [event.event_type for event in events] == ["llm.request", "llm.error"]
    assert events[1].payload["error"] == "upstream failed with Bearer [REDACTED]"
    assert ledger.verify("run-2") is True
