from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.knowledge import (
    KnowledgeCreateRequest,
    KnowledgeDocument,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from app.services.dependencies import AppServicesDep

router = APIRouter()


@router.get("", response_model=list[KnowledgeDocument])
async def list_documents(services: AppServicesDep) -> list[KnowledgeDocument]:
    return services.knowledge.list_documents()


@router.post("", response_model=KnowledgeDocument, status_code=status.HTTP_201_CREATED)
async def create_document(
    request: KnowledgeCreateRequest,
    services: AppServicesDep,
) -> KnowledgeDocument:
    return services.knowledge.create_document(
        title=request.title,
        content=request.content,
        metadata=request.metadata,
    )


@router.post("/search", response_model=list[KnowledgeSearchResult])
async def search_documents(
    request: KnowledgeSearchRequest,
    services: AppServicesDep,
) -> list[KnowledgeSearchResult]:
    return services.knowledge.search(query=request.query, limit=request.limit)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, services: AppServicesDep) -> None:
    deleted = services.knowledge.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
