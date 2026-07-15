from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from llm.base import LLMMessage, LLMProvider, LLMResponse
from llm.http_client import create_http_client


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
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = self._validate_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

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
        }

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        payload = {
            "model": kwargs.pop("model", self.model),
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
            "temperature": kwargs.pop("temperature", self.temperature),
            "stream": False,
        }
        payload.update(kwargs)

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
            response.raise_for_status()
            raw = response.json()

        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        return LLMResponse(
            content=str(message.get("content", "")),
            model=str(raw.get("model", payload["model"])),
            provider=self.name,
            raw=raw,
        )
