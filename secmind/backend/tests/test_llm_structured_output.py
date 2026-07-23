import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from ledger.runtime_store import RuntimeLedgerStore
from llm.base import EmptyContentReason, LLMMessage, LLMResponse
from llm.ledger import LedgerLLMProvider
from llm.openai_compatible import OpenAICompatibleProvider
from llm.structured_output import StructuredOutputError, parse_structured_output


class ResultSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    confidence: float


def provider(monkeypatch, response_body, captured=None):
    captured = captured if captured is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response_body)

    monkeypatch.setattr(
        "llm.openai_compatible.create_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://example.com/v1",
        model="deepseek-v4-flash",
        thinking_enabled=True,
        reasoning_effort="max",
    )


@pytest.mark.asyncio
async def test_provider_exposes_reasoning_only_length_and_usage(monkeypatch):
    model = provider(
        monkeypatch,
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "private reasoning"},
                }
            ],
            "usage": {
                "prompt_tokens": 58_853,
                "completion_tokens": 4_000,
                "total_tokens": 62_853,
                "prompt_cache_hit_tokens": 2_048,
                "completion_tokens_details": {"reasoning_tokens": 4_000},
            },
        },
    )

    response = await model.complete([LLMMessage(role="user", content="analyze")])

    assert response.finish_reason == "length"
    assert response.usage.prompt_tokens == 58_853
    assert response.usage.reasoning_tokens == 4_000
    assert response.usage.cache_read_tokens == 2_048
    assert response.empty_content_reason == EmptyContentReason.LENGTH_REASONING_ONLY
    assert response.should_retry_without_thinking is True


@pytest.mark.asyncio
async def test_call_level_thinking_override_disables_reasoning_effort(monkeypatch):
    captured = {}
    model = provider(
        monkeypatch,
        {
            "model": "deepseek-v4-flash",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
        },
        captured,
    )

    await model.complete(
        [LLMMessage(role="system", content="Return JSON")],
        response_schema={"type": "object"},
        json_mode=True,
        thinking_enabled=False,
        reasoning_effort="high",
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured
    assert "thinking_enabled" not in captured


@pytest.mark.parametrize(
    "content",
    [
        '{"answer":"ok","confidence":0.8}',
        '```json\n{"answer":"ok","confidence":0.8}\n```',
    ],
)
def test_strict_parser_accepts_complete_json_documents(content):
    result = parse_structured_output(content, ResultSchema)

    assert result.answer == "ok"
    assert result.confidence == 0.8


def test_strict_parser_rejects_prose_wrapped_json():
    with pytest.raises(StructuredOutputError) as captured:
        parse_structured_output(
            'Result: {"answer":"ok","confidence":0.8}',
            ResultSchema,
        )

    diagnostics = captured.value.diagnostics
    assert diagnostics.code == "invalid_json"
    assert diagnostics.source_format == "unknown"
    assert diagnostics.validation_errors[0]["type"] == "json_decode"


def test_schema_diagnostics_expose_field_paths_without_input_values():
    secret = "must-not-appear-in-diagnostics"
    with pytest.raises(StructuredOutputError) as captured:
        parse_structured_output(
            json.dumps({"answer": secret, "confidence": "invalid", "extra": secret}),
            ResultSchema,
        )

    diagnostics = captured.value.diagnostics
    assert diagnostics.code == "schema_validation"
    assert {tuple(item["location"]) for item in diagnostics.validation_errors} == {
        ("confidence",),
        ("extra",),
    }
    assert secret not in diagnostics.model_dump_json()


def test_reasoning_only_truncation_provides_bounded_retry_advice():
    response = LLMResponse(
        content="",
        model="deepseek-v4-flash",
        provider="deepseek",
        finish_reason="length",
        empty_content_reason=EmptyContentReason.LENGTH_REASONING_ONLY,
    )

    with pytest.raises(StructuredOutputError) as captured:
        parse_structured_output(response, ResultSchema)

    diagnostics = captured.value.diagnostics
    assert diagnostics.retryable is True
    assert diagnostics.suggested_overrides == {"thinking_enabled": False}


def test_reasoning_only_stop_provides_bounded_retry_advice():
    response = LLMResponse(
        content=" ",
        model="deepseek-v4-flash",
        provider="deepseek",
        finish_reason="stop",
        empty_content_reason=EmptyContentReason.REASONING_ONLY,
    )

    with pytest.raises(StructuredOutputError) as captured:
        parse_structured_output(response, ResultSchema)

    diagnostics = captured.value.diagnostics
    assert response.should_retry_without_thinking is True
    assert diagnostics.retryable is True
    assert diagnostics.suggested_overrides == {"thinking_enabled": False}


@pytest.mark.asyncio
async def test_ledger_records_normalized_response_diagnostics(tmp_path):
    class StaticProvider(OpenAICompatibleProvider):
        async def complete(self, messages, **kwargs):
            return LLMResponse(
                content="",
                model="deepseek-v4-flash",
                provider="deepseek",
                finish_reason="length",
                empty_content_reason=EmptyContentReason.LENGTH_REASONING_ONLY,
            )

    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'ledger.db'}")
    wrapped = LedgerLLMProvider(
        StaticProvider(
            name="deepseek",
            api_key="test-key",
            base_url="https://example.com/v1",
            model="deepseek-v4-flash",
        ),
        ledger,
    )

    await wrapped.complete([LLMMessage(role="user", content="analyze")], run_id="run-1")

    response_event = ledger.events("run-1")[-1]
    assert response_event.payload["finish_reason"] == "length"
    assert response_event.payload["usage"]["total_tokens"] == 0
    assert response_event.payload["empty_content_reason"] == "length_reasoning_only"
