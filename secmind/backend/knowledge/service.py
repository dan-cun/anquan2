from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from app.schemas.knowledge import KnowledgeDocument, KnowledgeSearchResult
from knowledge.embedding import QwenEmbeddingClient
from knowledge.models import VectorDocument, VerifierAttestation
from knowledge.qdrant_store import QdrantKnowledgeStore

if TYPE_CHECKING:
    from app.core.config import Settings


class EmbeddingProvider(Protocol):
    def embed_one(self, text: str) -> list[float]: ...


class QdrantKnowledgeService:
    """Router-compatible knowledge service backed by Qdrant and embeddings."""

    def __init__(
        self,
        *,
        store: QdrantKnowledgeStore,
        embeddings: EmbeddingProvider,
        memory_store: QdrantKnowledgeStore | None = None,
        default_source: str = "knowledge-api",
    ) -> None:
        self.store = store
        self.memory_store = memory_store or store
        self.embeddings = embeddings
        self.default_source = default_source

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantKnowledgeService:
        return cls(
            store=QdrantKnowledgeStore.from_settings(settings),
            memory_store=QdrantKnowledgeStore.from_settings(
                settings,
                collection_name=settings.qdrant_memory_collection,
            ),
            embeddings=QwenEmbeddingClient.from_settings(settings),
        )

    def create_document(
        self,
        *,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeDocument:
        document = VectorDocument(
            title=title,
            content=content,
            source=self.default_source,
            metadata=metadata or {},
        )
        self.store.upsert(document, self._embed_document(document))
        return document.as_api_document()

    def commit_episodic_memory(
        self,
        *,
        title: str,
        content: str,
        run_id: str,
        verification: VerifierAttestation,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeDocument:
        document = VectorDocument(
            title=title,
            content=content,
            source=run_id,
            kind="episodic",
            metadata=metadata or {},
            verification=verification,
        )
        document.require_verified_episodic_memory()
        self.memory_store.upsert(document, self._embed_document(document))
        return document.as_api_document()

    def search_episodic_memory(
        self,
        *,
        query: str,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeSearchResult]:
        filters = dict(metadata_filters or {})
        filters["kind"] = "episodic"
        vector = self.embeddings.embed_one(query)
        return [
            KnowledgeSearchResult(score=hit.score, document=hit.document.as_api_document())
            for hit in self.memory_store.search(vector, filters=filters, limit=limit)
        ]

    def list_documents(self) -> list[KnowledgeDocument]:
        documents = self.store.list()
        documents.sort(key=lambda item: item.updated_at, reverse=True)
        return [document.as_api_document() for document in documents]

    def search(
        self,
        *,
        query: str,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeSearchResult]:
        vector = self.embeddings.embed_one(query)
        return [
            KnowledgeSearchResult(score=hit.score, document=hit.document.as_api_document())
            for hit in self.store.search(vector, filters=metadata_filters, limit=limit)
        ]

    def delete_document(self, document_id: str) -> bool:
        return self.store.delete(document_id)

    def close(self) -> None:
        self.store.close()
        if self.memory_store is not self.store:
            self.memory_store.close()

    def _embed_document(self, document: VectorDocument) -> list[float]:
        return self.embeddings.embed_one(f"{document.title}\n{document.content}")
