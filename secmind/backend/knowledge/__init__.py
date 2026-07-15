"""Knowledge base abstractions."""

from knowledge.embedding import EmbeddingError, QwenEmbeddingClient
from knowledge.models import VectorDocument, VectorSearchHit, VerifierAttestation
from knowledge.qdrant_store import (
    QdrantDependencyError,
    QdrantKnowledgeStore,
)
from knowledge.service import EmbeddingProvider, QdrantKnowledgeService

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "QdrantDependencyError",
    "QdrantKnowledgeService",
    "QdrantKnowledgeStore",
    "QwenEmbeddingClient",
    "VectorDocument",
    "VectorSearchHit",
    "VerifierAttestation",
]
