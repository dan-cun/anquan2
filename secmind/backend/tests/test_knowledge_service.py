from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from app.core.config import Settings
from knowledge.models import VerifierAttestation
from knowledge.qdrant_store import QdrantKnowledgeStore
from knowledge.service import QdrantKnowledgeService


class KeywordEmbeddings:
    def embed_one(self, text: str) -> list[float]:
        lowered = text.lower()
        if "network" in lowered:
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]


def knowledge_service() -> QdrantKnowledgeService:
    memory_store = QdrantKnowledgeStore(
        collection_name="memory-service",
        vector_size=3,
        client=QdrantClient(":memory:"),
    )
    return QdrantKnowledgeService(
        store=QdrantKnowledgeStore(
            collection_name="service",
            vector_size=3,
            client=QdrantClient(":memory:"),
        ),
        embeddings=KeywordEmbeddings(),
        memory_store=memory_store,
    )


def test_service_can_be_built_from_shared_settings(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        llm_provider="qwen",
        llm_api_key="test-key",
        llm_base_url="https://dashscope.example/compatible-mode/v1",
        llm_embedding_model="text-embedding-v3",
        qdrant_url=":memory:",
        qdrant_collection="settings-knowledge",
        qdrant_memory_collection="settings-memory",
        qdrant_vector_size=3,
    )

    service = QdrantKnowledgeService.from_settings(settings)

    assert service.store.collection_name == "settings-knowledge"
    assert service.memory_store.collection_name == "settings-memory"
    assert service.embeddings.model == "text-embedding-v3"


def test_service_is_compatible_with_existing_knowledge_router_contract() -> None:
    service = knowledge_service()
    code = service.create_document(
        title="Code audit",
        content="Review Python subprocess usage.",
        metadata={"topic": "code"},
    )
    network = service.create_document(
        title="Network triage",
        content="Review traffic anomalies.",
        metadata={"topic": "network"},
    )

    assert {document.id for document in service.list_documents()} == {code.id, network.id}
    results = service.search(query="network", metadata_filters={"topic": "network"})
    assert [result.document.id for result in results] == [network.id]
    assert service.delete_document(code.id) is True
    assert service.delete_document(code.id) is False


def test_service_requires_verified_attestation_for_episodic_memory() -> None:
    service = knowledge_service()
    rejected = VerifierAttestation(
        run_id="run-1",
        verification_event_id="event-rejected",
        verifier_id="verifier-agent",
        verdict="rejected",
    )
    accepted = rejected.model_copy(
        update={"verification_event_id": "event-accepted", "verdict": "verified"}
    )

    with pytest.raises(ValueError, match="Verifier verification"):
        service.commit_episodic_memory(
            title="Rejected lesson",
            content="This must not enter long-term memory.",
            run_id="run-1",
            verification=rejected,
        )

    stored = service.commit_episodic_memory(
        title="Accepted lesson",
        content="This may enter long-term memory.",
        run_id="run-1",
        verification=accepted,
        metadata={"topic": "incident-response"},
    )
    assert stored.id not in {document.id for document in service.list_documents()}
    memory_results = service.search_episodic_memory(
        query="lesson",
        metadata_filters={"topic": "incident-response"},
    )
    assert [result.document.id for result in memory_results] == [stored.id]
