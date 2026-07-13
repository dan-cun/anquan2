from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from app.schemas.knowledge import KnowledgeDocument, KnowledgeSearchResult


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryKnowledgeStore:
    """Placeholder knowledge store. Replace with pgvector/GraphRAG later."""

    def __init__(self) -> None:
        self._documents: dict[str, KnowledgeDocument] = {}
        self._lock = RLock()

    def create_document(
        self,
        *,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeDocument:
        timestamp = _now()
        document = KnowledgeDocument(
            id=str(uuid4()),
            title=title,
            content=content,
            metadata=metadata or {},
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._lock:
            self._documents[document.id] = document
        return document

    def list_documents(self) -> list[KnowledgeDocument]:
        with self._lock:
            return sorted(self._documents.values(), key=lambda item: item.updated_at, reverse=True)

    def search(self, *, query: str, limit: int = 10) -> list[KnowledgeSearchResult]:
        normalized = query.lower()
        with self._lock:
            results: list[KnowledgeSearchResult] = []
            for document in self._documents.values():
                haystack = f"{document.title}\n{document.content}".lower()
                if normalized in haystack:
                    results.append(KnowledgeSearchResult(score=1.0, document=document))
            return results[:limit]

    def delete_document(self, document_id: str) -> bool:
        with self._lock:
            return self._documents.pop(document_id, None) is not None
