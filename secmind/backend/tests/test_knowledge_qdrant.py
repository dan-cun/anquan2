from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from knowledge.models import VectorDocument, VerifierAttestation
from knowledge.qdrant_store import QdrantKnowledgeStore


def memory_store(collection_name: str = "knowledge") -> QdrantKnowledgeStore:
    return QdrantKnowledgeStore(
        collection_name=collection_name,
        vector_size=3,
        client=QdrantClient(":memory:"),
    )


def test_qdrant_store_supports_memory_url_without_an_injected_client() -> None:
    store = QdrantKnowledgeStore(
        url=":memory:",
        collection_name="memory-url",
        vector_size=3,
    )
    store.ensure_collection()
    assert store.client.collection_exists("memory-url")


def test_qdrant_crud_search_and_metadata_filter() -> None:
    store = memory_store()
    code = VectorDocument(
        title="Bandit shell injection",
        content="Bandit detects unsafe subprocess calls.",
        source="ATT&CK",
        version="2026.1",
        metadata={"topic": "code", "severity": "high"},
    )
    network = VectorDocument(
        title="Network triage",
        content="Inspect unusual traffic.",
        source="internal",
        metadata={"topic": "network", "severity": "medium"},
    )
    store.upsert(code, [1.0, 0.0, 0.0])
    store.upsert(network, [0.0, 1.0, 0.0])

    assert store.get(code.id) == code
    assert {item.id for item in store.list()} == {code.id, network.id}
    hits = store.search(
        [1.0, 0.0, 0.0],
        filters={"topic": "code", "source": "ATT&CK"},
        limit=5,
    )
    assert [hit.document.id for hit in hits] == [code.id]
    assert hits[0].score > 0.99
    assert [item.id for item in store.list(filters={"metadata.severity": "high"})] == [
        code.id
    ]

    assert store.delete(code.id) is True
    assert store.delete(code.id) is False
    assert store.get(code.id) is None


def test_qdrant_rejects_unverified_or_mismatched_episodic_memory() -> None:
    store = memory_store("episodic")
    unverified = VectorDocument(
        title="Run lesson",
        content="A candidate lesson from a previous run.",
        source="run-1",
        kind="episodic",
    )
    rejected = unverified.model_copy(
        update={
            "verification": VerifierAttestation(
                run_id="run-1",
                verification_event_id="event-1",
                verifier_id="verifier-agent",
                verdict="rejected",
            )
        }
    )
    mismatched = unverified.model_copy(
        update={
            "verification": VerifierAttestation(
                run_id="another-run",
                verification_event_id="event-2",
                verifier_id="verifier-agent",
                verdict="verified",
            )
        }
    )

    with pytest.raises(ValueError, match="Verifier verification"):
        store.upsert(unverified, [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="Verifier verification"):
        store.upsert(rejected, [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="run_id"):
        store.upsert(mismatched, [1.0, 0.0, 0.0])


def test_qdrant_accepts_verified_episodic_memory_and_checks_vector_size() -> None:
    store = memory_store("verified-episodic")
    document = VectorDocument(
        title="Verified lesson",
        content="The verifier accepted this reusable lesson.",
        source="run-1",
        kind="episodic",
        verification=VerifierAttestation(
            run_id="run-1",
            verification_event_id="event-3",
            verifier_id="verifier-agent",
            verdict="verified",
            evidence_ids=["evidence-1"],
        ),
    )

    store.upsert(document, [1.0, 0.0, 0.0])
    assert store.get(document.id) == document
    with pytest.raises(ValueError, match="Expected vector size"):
        store.search([1.0])
