from __future__ import annotations

from app.core.config import Settings
from llm.base import LLMProvider, NullLLMProvider
from llm.openai_compatible import OpenAICompatibleProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider in {"", "null", "none", "disabled"}:
        return NullLLMProvider()

    if provider in {"qwen", "dashscope", "openai-compatible"}:
        if settings.llm_api_key is None:
            return NullLLMProvider(
                "LLM provider is set to qwen, but SECMIND_LLM_API_KEY is not configured."
            )
        return OpenAICompatibleProvider(
            name="qwen",
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    return NullLLMProvider(f"Unsupported LLM provider: {provider}")
