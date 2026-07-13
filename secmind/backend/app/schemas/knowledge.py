from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeDocument(BaseModel):
    id: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class KnowledgeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchResult(BaseModel):
    score: float
    document: KnowledgeDocument

