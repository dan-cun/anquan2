from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from app.schemas.knowledge import KnowledgeDocument


def utc_now() -> datetime:
    return datetime.now(UTC)


class VerifierAttestation(BaseModel):
    """Auditable proof that a verifier accepted an episodic-memory candidate."""

    run_id: str = Field(min_length=1)
    verification_event_id: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    verdict: Literal["verified", "rejected"]
    evidence_ids: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=utc_now)


class VectorDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(min_length=1)
    version: str = Field(default="1", min_length=1)
    kind: Literal["knowledge", "episodic"] = "knowledge"
    metadata: dict[str, Any] = Field(default_factory=dict)
    verification: VerifierAttestation | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identifier(self) -> VectorDocument:
        try:
            UUID(self.id)
        except ValueError as error:
            raise ValueError("Vector document id must be a UUID") from error
        return self

    def require_verified_episodic_memory(self) -> None:
        if self.kind != "episodic":
            return
        if self.verification is None or self.verification.verdict != "verified":
            raise ValueError(
                "Episodic memory must pass Verifier verification before it can be stored"
            )
        if self.verification.run_id != self.source:
            raise ValueError("Verifier run_id must match the episodic-memory source")

    def as_api_document(self) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=self.id,
            title=self.title,
            content=self.content,
            metadata=self.metadata,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class VectorSearchHit(BaseModel):
    score: float
    document: VectorDocument
