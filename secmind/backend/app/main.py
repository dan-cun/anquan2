from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import API_CONTRACT_VERSION, api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import install_security_middleware
from app.schemas.events import WS_PROTOCOL_VERSION
from app.services.context import open_services
from app.websocket.manager import ConnectionManager
from app.websocket.router import websocket_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI):
        async with open_services(resolved_settings) as services:
            lifespan_app.state.services = services
            yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description="Extensible backend scaffold for SecMind.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_security_middleware(app, resolved_settings)

    app.state.settings = resolved_settings
    app.state.ws_manager = ConnectionManager()

    @app.get("/", tags=["root"])
    async def root() -> dict[str, object]:
        return {
            "name": resolved_settings.app_name,
            "version": resolved_settings.app_version,
            "api": resolved_settings.api_prefix,
            "schema_version": API_CONTRACT_VERSION,
            "websocket_protocol_version": WS_PROTOCOL_VERSION,
            "health": "/health",
            "websocket": "/ws/flows/{flow_id}",
            "runtime_events": f"{resolved_settings.api_prefix}/runs/{{run_id}}/events",
        }

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": resolved_settings.app_name,
            "version": resolved_settings.app_version,
            "checkpoint_backend": resolved_settings.checkpoint_backend,
            "projection_enabled": resolved_settings.projection_enabled,
            "knowledge_backend": app.state.services.knowledge_backend,
        }

    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    app.include_router(websocket_router)
    return app


app = create_app()
