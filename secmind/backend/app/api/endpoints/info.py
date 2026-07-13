from __future__ import annotations

from fastapi import APIRouter

from app.services.dependencies import AppServicesDep, SettingsDep

router = APIRouter()


@router.get("/info")
async def get_info(
    settings: SettingsDep,
    services: AppServicesDep,
) -> dict[str, object]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "apiPrefix": settings.api_prefix,
        "visualEntry": "fronted",
        "featurePages": [
            {"key": "workbench", "path": "/workbench", "status": "reserved"},
            {"key": "audit", "path": "/audit", "status": "reserved"},
            {"key": "knowledge", "path": "/knowledge", "status": "reserved"},
            {"key": "settings", "path": "/settings", "status": "reserved"},
        ],
        "extensions": {
            "tools": services.tool_registry.list_metadata(),
            "llmProvider": services.llm_provider.metadata(),
            "sandbox": services.sandbox.name,
        },
    }
