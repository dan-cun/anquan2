from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.context import build_services
from app.websocket.manager import ConnectionManager
from app.websocket.router import websocket_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description="Extensible backend scaffold for SecMind.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = resolved_settings
    app.state.services = build_services(resolved_settings)
    app.state.ws_manager = ConnectionManager()

    @app.get("/", tags=["root"])
    async def root() -> dict[str, object]:
        return {
            "name": resolved_settings.app_name,
            "version": resolved_settings.app_version,
            "api": resolved_settings.api_prefix,
            "health": "/health",
            "websocket": "/ws/flows/{flow_id}",
        }

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": resolved_settings.app_name,
            "version": resolved_settings.app_version,
        }

    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    app.include_router(websocket_router)
    return app


app = create_app()

