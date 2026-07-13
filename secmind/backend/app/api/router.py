from fastapi import APIRouter

from app.api.endpoints import flows, info, knowledge, ledger

api_router = APIRouter()
api_router.include_router(info.router, tags=["info"])
api_router.include_router(flows.router, prefix="/flows", tags=["flows"])
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])

