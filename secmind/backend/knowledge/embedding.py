from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from app.core.config import Settings


class EmbeddingError(RuntimeError):
    pass


class QwenEmbeddingClient:
    """Synchronous OpenAI-compatible embedding client for Qwen/DashScope."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-v3",
        timeout_seconds: float = 30.0,
        expected_vector_size: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Qwen embedding API key is required")
        if not model.strip():
            raise ValueError("Qwen embedding model is required")
        if timeout_seconds <= 0:
            raise ValueError("Qwen embedding timeout must be positive")
        if expected_vector_size is not None and expected_vector_size < 1:
            raise ValueError("Expected embedding vector size must be positive")
        self.api_key = api_key
        self.base_url = self._validate_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.expected_vector_size = expected_vector_size
        self.transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> QwenEmbeddingClient:
        api_key = settings.resolved_llm_api_key
        if api_key is None:
            raise ValueError("Qwen embedding API key is not configured")
        return cls(
            api_key=api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_embedding_model,
            timeout_seconds=settings.llm_timeout_seconds,
            expected_vector_size=settings.qdrant_vector_size,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str):
            raise TypeError("Embedding input must be a sequence of strings")
        normalized = [text.strip() for text in texts]
        if not normalized or any(not text for text in normalized):
            raise ValueError("Embedding input must contain non-empty text")

        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": normalized},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as error:
            raise EmbeddingError(
                f"Qwen embedding request failed with HTTP {error.response.status_code}"
            ) from None
        except (httpx.HTTPError, ValueError) as error:
            raise EmbeddingError(
                f"Qwen embedding request failed ({type(error).__name__})"
            ) from None

        vectors = self._parse_vectors(payload, expected_count=len(normalized))
        if self.expected_vector_size is not None:
            for vector in vectors:
                if len(vector) != self.expected_vector_size:
                    raise EmbeddingError(
                        "Qwen embedding response has an unexpected vector dimension"
                    )
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @staticmethod
    def _parse_vectors(payload: Any, *, expected_count: int) -> list[list[float]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingError("Qwen embedding response is missing data")
        indexed_vectors: list[tuple[int, list[float]]] = []
        for position, item in enumerate(payload["data"]):
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise EmbeddingError("Qwen embedding response contains an invalid item")
            try:
                vector = [float(value) for value in item["embedding"]]
                index = int(item.get("index", position))
            except (TypeError, ValueError) as error:
                raise EmbeddingError("Qwen embedding response contains invalid values") from error
            if not vector:
                raise EmbeddingError("Qwen embedding response contains an empty vector")
            indexed_vectors.append((index, vector))
        indexed_vectors.sort(key=lambda item: item[0])
        if [index for index, _ in indexed_vectors] != list(range(expected_count)):
            raise EmbeddingError("Qwen embedding response contains invalid indexes")
        vectors = [vector for _, vector in indexed_vectors]
        if len(vectors) != expected_count:
            raise EmbeddingError("Qwen embedding response count does not match the request")
        return vectors

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlparse(base_url.strip().rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Embedding base_url must be an HTTPS URL with a hostname")
        if parsed.username or parsed.password:
            raise ValueError("Embedding base_url must not contain embedded credentials")
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
            raise ValueError("Embedding base_url must not target a private or local address")
        return parsed.geturl()
