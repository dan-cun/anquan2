from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.schemas.provider import ProviderMessage, ProviderToolCall
from llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderHTTPError,
    empty_content_reason,
)
from llm.http_client import create_http_client
from llm.provider_request import ProviderRequest
from tools.safety import redact_tool_value, safe_error_message


class OpenAICompatibleProvider(LLMProvider):
    """Minimal chat-completions client for OpenAI-compatible model endpoints."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        temperature: float = 0.2,
        thinking_enabled: bool = True,
        reasoning_effort: str = "max",
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = self._validate_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.thinking_enabled = thinking_enabled
        self.reasoning_effort = reasoning_effort

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlparse(base_url.strip().rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("LLM base_url must be an HTTPS URL with a hostname")
        if parsed.username or parsed.password:
            raise ValueError("LLM base_url must not contain embedded credentials")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("LLM base_url must not target a private or local address")
        return parsed.geturl()

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": True,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "thinking_enabled": self.thinking_enabled,
            "reasoning_effort": self.reasoning_effort,
        }

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        model = kwargs.pop("model", self.model)
        temperature = kwargs.pop("temperature", self.temperature)
        response_schema = kwargs.pop("response_schema", None)
        json_mode = bool(kwargs.pop("json_mode", response_schema is not None))
        thinking_enabled = bool(kwargs.pop("thinking_enabled", self.thinking_enabled))
        reasoning_effort = kwargs.pop("reasoning_effort", self.reasoning_effort)
        request_values: dict[str, Any] = {
            "model": model,
            "messages": [
                ProviderMessage.model_validate(
                    message.model_dump(mode="python", exclude={"metadata"})
                )
                for message in messages
            ],
            "temperature": temperature,
            "stream": False,
        }
        request_values.update(kwargs)
        if json_mode:
            if self.name == "deepseek":
                request_values["response_format"] = {"type": "json_object"}
                request_values["thinking"] = {
                    "type": "enabled" if thinking_enabled else "disabled"
                }
                if thinking_enabled and reasoning_effort:
                    request_values["reasoning_effort"] = str(reasoning_effort)
                if isinstance(response_schema, dict):
                    schema_text = json.dumps(
                        response_schema,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    first_message = request_values["messages"][0]
                    request_values["messages"][0] = first_message.model_copy(
                        update={
                            "content": (first_message.content or "")
                            + "\nReturn exactly one JSON object matching this schema: "
                            + schema_text
                        }
                    )
            elif isinstance(response_schema, dict):
                request_values["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "secmind_output", "schema": response_schema},
                }
            else:
                request_values["response_format"] = {"type": "json_object"}
        try:
            request = ProviderRequest.model_validate(request_values)
        except ValidationError as error:
            fields = sorted(
                ".".join(str(part) for part in item["loc"])
                for item in error.errors(include_url=False)
            )
            raise ValueError(
                "Unsupported or invalid chat-completions parameter(s): " + ", ".join(fields)
            ) from error
        payload = request.payload()

        async with create_http_client() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            if response.status_code >= 400:
                raise ProviderHTTPError(
                    response.status_code,
                    self._error_diagnostics(
                        response=response,
                        payload=payload,
                        response_schema=response_schema,
                    ),
                )
            raw = response.json()

        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        tool_calls = [
            ProviderToolCall.model_validate(item) for item in message.get("tool_calls") or []
        ]
        content = str(message.get("content") or "")
        finish_reason = str(choice.get("finish_reason")) if choice.get("finish_reason") else None
        reasoning_content = str(message.get("reasoning_content") or "")
        return LLMResponse(
            content=content,
            model=str(raw.get("model", payload["model"])),
            provider=self.name,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=LLMUsage.from_provider(raw.get("usage")),
            empty_content_reason=empty_content_reason(
                content=content,
                finish_reason=finish_reason,
                reasoning_content=reasoning_content,
                has_tool_calls=bool(tool_calls),
            ),
            raw=raw,
        )

    @staticmethod
    def _error_diagnostics(
        *,
        response: Any,
        payload: dict[str, Any],
        response_schema: Any,
    ) -> dict[str, Any]:
        try:
            response_body = redact_tool_value(response.json())
        except (ValueError, TypeError):
            response_body = safe_error_message(response.text, max_length=4_000)
        messages = payload.get("messages")
        message_items = messages if isinstance(messages, list) else []
        character_count = sum(
            len(str(item.get("content") or "")) for item in message_items if isinstance(item, dict)
        )
        schema_size = (
            len(
                json.dumps(
                    response_schema,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if isinstance(response_schema, dict)
            else 0
        )
        return {
            "status_code": response.status_code,
            "response_body": response_body,
            "request_fields": sorted(payload),
            "message_count": len(message_items),
            "character_count": character_count,
            "schema_size_bytes": schema_size,
        }
