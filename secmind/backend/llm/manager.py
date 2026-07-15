from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse
from llm.factory import build_llm_provider
from llm.ledger import LedgerLLMProvider

ProviderFactory = Callable[[Settings], LLMProvider]
CONFIG_AUDIT_RUN_ID = "system-model-config"


class ModelConfigurationError(RuntimeError):
    pass


class ModelConnectionError(RuntimeError):
    pass


class LLMProviderManager(LLMProvider):
    """Own the active provider and swap it only after candidate validation."""

    name = "managed"

    def __init__(
        self,
        *,
        settings: Settings,
        ledger: RuntimeLedgerStore,
        provider_factory: ProviderFactory = build_llm_provider,
    ) -> None:
        self._lock = asyncio.Lock()
        self._ledger = ledger
        self._factory = provider_factory
        self._settings = settings
        self._api_key = settings.resolved_llm_api_key
        self._provider = self._wrap(self._factory(self._settings_with_key(settings, self._api_key)))
        self._updated_at = datetime.now(UTC)

    def metadata(self) -> dict[str, Any]:
        metadata = self._provider.metadata().copy()
        metadata.update(
            {
                "managed": True,
                "provider": self._settings.llm_provider,
                "api_key_configured": self._api_key is not None,
                "updated_at": self._updated_at.isoformat(),
            }
        )
        return metadata

    def configuration(self) -> dict[str, Any]:
        metadata = self._provider.metadata()
        return {
            "provider": self._settings.llm_provider,
            "model": self._settings.llm_model,
            "base_url": self._settings.llm_base_url,
            "api_key_configured": self._api_key is not None,
            "configured": bool(metadata.get("configured")),
            "updated_at": self._updated_at,
        }

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        async with self._lock:
            provider = self._provider
        return await provider.complete(messages, **kwargs)

    async def test_configuration(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        candidate_settings, candidate_key = await self._candidate_settings(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        candidate = self._factory(candidate_settings)
        try:
            result = await self._probe(candidate, candidate_key)
        except Exception as error:
            self._audit(
                "model.config.tested",
                candidate_settings,
                {"ok": False, "error_type": type(error).__name__},
            )
            raise
        self._audit("model.config.tested", candidate_settings, result)
        return result

    async def apply_configuration(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str | None,
        test_connection: bool = True,
    ) -> dict[str, Any]:
        candidate_settings, candidate_key = await self._candidate_settings(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        raw_candidate = self._factory(candidate_settings)
        if test_connection:
            try:
                probe_result = await self._probe(raw_candidate, candidate_key)
            except Exception as error:
                self._audit(
                    "model.config.rejected",
                    candidate_settings,
                    {"ok": False, "error_type": type(error).__name__},
                )
                raise
        else:
            probe_result = {"ok": None, "message": "Connection test skipped"}
        candidate = self._wrap(raw_candidate)
        async with self._lock:
            self._settings = candidate_settings
            self._api_key = candidate_key
            self._provider = candidate
            self._updated_at = datetime.now(UTC)
        self._audit("model.config.updated", candidate_settings, probe_result)
        return self.configuration()

    async def _candidate_settings(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str | None,
    ) -> tuple[Settings, str | None]:
        async with self._lock:
            current_settings = self._settings
            current_key = self._api_key
        endpoint_changed = base_url.rstrip("/") != current_settings.llm_base_url.rstrip("/")
        provider_changed = provider != current_settings.llm_provider
        may_reuse_key = not endpoint_changed and not provider_changed
        candidate_key = api_key if api_key is not None else (
            current_key if may_reuse_key else None
        )
        if candidate_key is None:
            raise ModelConfigurationError(
                "A model API key is required when the provider or Base URL changes"
            )
        candidate_settings = current_settings.model_copy(
            update={
                "llm_provider": provider,
                "llm_model": model,
                "llm_base_url": base_url,
                "llm_api_key": SecretStr(candidate_key) if candidate_key else None,
                "llm_api_key_file": None,
            }
        )
        candidate = self._factory(candidate_settings)
        if not candidate.metadata().get("configured"):
            raise ModelConfigurationError("A model API key is required")
        return candidate_settings, candidate_key

    async def _probe(self, provider: LLMProvider, api_key: str | None) -> dict[str, Any]:
        if api_key is None or not provider.metadata().get("configured"):
            raise ModelConfigurationError("A model API key is required")
        started = time.perf_counter()
        try:
            response = await provider.complete(
                [LLMMessage(role="user", content="Reply with OK only.")],
                temperature=0,
                max_tokens=2,
            )
        except Exception as error:
            raise ModelConnectionError(
                f"Model connection failed ({type(error).__name__})"
            ) from error
        return {
            "ok": True,
            "provider": response.provider,
            "model": response.model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "message": "Model connection succeeded",
        }

    def _wrap(self, provider: LLMProvider) -> LedgerLLMProvider:
        return LedgerLLMProvider(provider, self._ledger)

    def _audit(
        self,
        event_type: str,
        settings: Settings,
        result: dict[str, Any],
    ) -> None:
        self._ledger.append(
            CONFIG_AUDIT_RUN_ID,
            event_type=event_type,
            actor="model_config_api",
            payload={
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
                "result": result,
            },
        )

    @staticmethod
    def _settings_with_key(settings: Settings, api_key: str | None) -> Settings:
        return settings.model_copy(
            update={
                "llm_api_key": SecretStr(api_key) if api_key else None,
                "llm_api_key_file": None,
            }
        )
