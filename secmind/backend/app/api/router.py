from fastapi import APIRouter

from app.api.endpoints import flows, info, knowledge, ledger, model_config, runtime

API_CONTRACT_VERSION = "1.0"

api_router = APIRouter(responses={500: {"description": "Internal server error"}})
api_router.include_router(info.router, tags=["info"])
api_router.include_router(model_config.router, tags=["model-config"])
api_router.include_router(runtime.router, tags=["runtime"])
api_router.include_router(flows.router, prefix="/flows", tags=["flows"])
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
