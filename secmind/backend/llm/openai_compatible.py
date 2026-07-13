from __future__ import annotations

from typing import Any

import httpx

from llm.base import LLMMessage, LLMProvider, LLMResponse


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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

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

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
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
