from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.ledger import LedgerAnchor, LedgerEntry, LedgerVerifyResponse
from app.services.dependencies import AppServicesDep

router = APIRouter()


@router.get("/{flow_id}", response_model=list[LedgerEntry])
async def list_ledger_entries(
    flow_id: str,
    services: AppServicesDep,
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[LedgerEntry]:
    try:
        return services.ledger.list_entries(flow_id=flow_id, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{flow_id}/verify", response_model=LedgerVerifyResponse)
async def verify_ledger(
    flow_id: str,
    services: AppServicesDep,
) -> LedgerVerifyResponse:
    try:
        return services.ledger.verify(flow_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{flow_id}/anchors", response_model=list[LedgerAnchor])
async def list_ledger_anchors(
    flow_id: str,
    services: AppServicesDep,
) -> list[LedgerAnchor]:
    try:
        return services.ledger.list_anchors(flow_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
