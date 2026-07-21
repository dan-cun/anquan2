from __future__ import annotations

from app.core.config import Settings
from llm.base import LLMProvider, NullLLMProvider
from llm.openai_compatible import OpenAICompatibleProvider

OPENAI_COMPATIBLE_PROVIDERS = {
    "qwen": "qwen",
    "dashscope": "qwen",
    "deepseek": "deepseek",
    "openai": "openai",
    "moonshot": "moonshot",
    "zhipu": "zhipu",
    "siliconflow": "siliconflow",
    "openai-compatible": "openai-compatible",
}


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider in {"", "null", "none", "disabled"}:
        return NullLLMProvider()

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        api_key = settings.resolved_llm_api_key
        if api_key is None:
            return NullLLMProvider(
                f"LLM provider is set to {provider}, but SECMIND_LLM_API_KEY is not configured."
            )
        return OpenAICompatibleProvider(
            name=OPENAI_COMPATIBLE_PROVIDERS[provider],
            api_key=api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            thinking_enabled=settings.llm_thinking_enabled,
            reasoning_effort=settings.llm_reasoning_effort,
        )

    return NullLLMProvider(f"Unsupported LLM provider: {provider}")
