from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING, Any

from knowledge.models import VectorDocument, VectorSearchHit

if TYPE_CHECKING:
    from app.core.config import Settings


class QdrantDependencyError(RuntimeError):
    pass


class QdrantKnowledgeStore:
    """Qdrant adapter for versioned knowledge and verified episodic memory."""

    def __init__(
        self,
        *,
        collection_name: str,
        vector_size: int,
        url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        client: Any | None = None,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("Qdrant collection name is required")
        if vector_size < 1:
            raise ValueError("Qdrant vector size must be positive")
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._collection_lock = RLock()
        self.client = client or self._create_client(
            url=url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        collection_name: str | None = None,
    ) -> QdrantKnowledgeStore:
        return cls(
            url=settings.qdrant_url,
            api_key=settings.resolved_qdrant_api_key,
            collection_name=collection_name or settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )

    @staticmethod
    def _create_client(*, url: str | None, api_key: str | None, timeout_seconds: float) -> Any:
        try:
            from qdrant_client import QdrantClient
        except ModuleNotFoundError as error:
            raise QdrantDependencyError(
                "Install the qdrant extra to use QdrantKnowledgeStore"
            ) from error
        if not url:
            raise ValueError("Qdrant URL is required when no client is supplied")
        if url == ":memory:":
            return QdrantClient(":memory:")
        return QdrantClient(url=url, api_key=api_key, timeout=max(1, int(timeout_seconds)))

    @staticmethod
    def _models() -> Any:
        try:
            from qdrant_client import models
        except ModuleNotFoundError as error:
            raise QdrantDependencyError(
                "Install the qdrant extra to use QdrantKnowledgeStore"
            ) from error
        return models

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        with self._collection_lock:
            if self.client.collection_exists(self.collection_name):
                return
            models = self._models()
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
            except Exception:
                if not self.client.collection_exists(self.collection_name):
                    raise

    def upsert(self, document: VectorDocument, vector: list[float]) -> None:
        self._validate_vector(vector)
        document.require_verified_episodic_memory()
        self.ensure_collection()
        models = self._models()
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=document.id,
                    vector=vector,
                    payload=document.model_dump(mode="json"),
                )
            ],
            wait=True,
        )

    def get(self, document_id: str) -> VectorDocument | None:
        self.ensure_collection()
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[document_id],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return None
        return self._document_from_payload(records[0].payload)

    def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 1000,
    ) -> list[VectorDocument]:
        if limit < 1:
            return []
        self.ensure_collection()
        records, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=self._build_filter(filters),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [self._document_from_payload(record.payload) for record in records]

    def delete(self, document_id: str) -> bool:
        if self.get(document_id) is None:
            return False
        models = self._models()
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[document_id]),
            wait=True,
        )
        return True

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def search(
        self,
        vector: list[float],
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        self._validate_vector(vector)
        if limit < 1:
            return []
        self.ensure_collection()
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=self._build_filter(filters),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [
            VectorSearchHit(
                score=max(0.0, min(1.0, float(point.score))),
                document=self._document_from_payload(point.payload),
            )
            for point in response.points
        ]

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.vector_size:
            raise ValueError(f"Expected vector size {self.vector_size}, got {len(vector)}")

    def _build_filter(self, filters: dict[str, Any] | None) -> Any | None:
        if not filters:
            return None
        models = self._models()
        conditions = []
        direct_fields = {"id", "source", "version", "kind"}
        for key, value in filters.items():
            if isinstance(value, (dict, list, set, tuple)):
                raise ValueError(f"Qdrant filter {key!r} must use a scalar value")
            payload_key = key if key in direct_fields or key.startswith("metadata.") else (
                f"metadata.{key}"
            )
            conditions.append(
                models.FieldCondition(key=payload_key, match=models.MatchValue(value=value))
            )
        return models.Filter(must=conditions)

    @staticmethod
    def _document_from_payload(payload: Any) -> VectorDocument:
        if not isinstance(payload, dict):
            raise ValueError("Qdrant point is missing a valid document payload")
        return VectorDocument.model_validate(payload)
