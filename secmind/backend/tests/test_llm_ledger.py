import json

import httpx
import pytest

from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse
from llm.ledger import LedgerLLMProvider
from llm.openai_compatible import OpenAICompatibleProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(kwargs)
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


@pytest.mark.asyncio
async def test_runtime_trace_parameters_are_not_forwarded_to_provider(tmp_path):
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'ledger.db'}")
    upstream = FakeProvider()
    provider = LedgerLLMProvider(upstream, ledger)

    await provider.complete(
        [LLMMessage(role="user", content="inspect this")],
        run_id="run-trace",
        flow_id="flow-trace",
        task_id="task-trace",
        agent_instance_id="agent-trace",
        stage="agent.assistant",
        model_profile="worker",
        iteration=3,
        temperature=0.1,
        max_tokens=64,
    )

    assert upstream.calls == [{"temperature": 0.1, "max_tokens": 64}]
    event = ledger.events("run-trace")[0]
    assert event.context.agent_instance_id == "agent-trace"
    assert event.payload["parameters"] == {"temperature": 0.1, "max_tokens": 64}
    assert event.payload["trace_parameters"] == {
        "agent_instance_id": "agent-trace",
        "iteration": 3,
        "model_profile": "worker",
        "stage": "agent.assistant",
    }


@pytest.mark.asyncio
async def test_http_400_diagnostics_are_redacted_and_recorded(tmp_path, monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "token=super-secret invalid request"}},
        )

    monkeypatch.setattr(
        "llm.openai_compatible.create_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'ledger.db'}")
    provider = LedgerLLMProvider(
        OpenAICompatibleProvider(
            name="deepseek",
            api_key="test-key",
            base_url="https://example.com/v1",
            model="deepseek-v4-flash",
        ),
        ledger,
    )

    with pytest.raises(Exception, match="HTTP 400"):
        await provider.complete(
            [LLMMessage(role="user", content="inspect this")],
            run_id="run-400",
            stage="agent.assistant",
            response_schema={"type": "object"},
            json_mode=True,
            max_tokens=64,
        )

    error_event = ledger.events("run-400")[-1]
    diagnostics = error_event.payload["diagnostics"]
    assert diagnostics["status_code"] == 400
    assert diagnostics["message_count"] == 1
    assert diagnostics["character_count"] > len("inspect this")
    assert diagnostics["schema_size_bytes"] > 0
    assert diagnostics["request_fields"] == sorted(diagnostics["request_fields"])
    assert "super-secret" not in str(diagnostics["response_body"])
    assert "[REDACTED]" in str(diagnostics["response_body"])


@pytest.mark.asyncio
async def test_deepseek_json_controls_are_mapped_without_trace_fields(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": '{"ok":true}'}}],
            },
        )

    monkeypatch.setattr(
        "llm.openai_compatible.create_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://example.com/v1",
        model="deepseek-v4-flash",
        thinking_enabled=True,
        reasoning_effort="max",
    )

    await provider.complete(
        [LLMMessage(role="system", content="Return JSON")],
        response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        json_mode=True,
        max_tokens=64,
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"
    assert "schema" in captured["messages"][0]["content"].lower()
    assert not {
        "stage",
        "model_profile",
        "agent_instance_id",
        "iteration",
        "run_id",
        "flow_id",
        "task_id",
        "response_schema",
        "json_mode",
    }.intersection(captured)


@pytest.mark.asyncio
async def test_provider_request_rejects_unknown_transport_field() -> None:
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://example.com/v1",
        model="deepseek-v4-flash",
    )

    with pytest.raises(ValueError, match="internal_only"):
        await provider.complete(
            [LLMMessage(role="user", content="hello")],
            internal_only="must-not-cross-provider-boundary",
        )
