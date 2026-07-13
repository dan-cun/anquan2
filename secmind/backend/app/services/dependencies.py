from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.context import AppServices
from app.websocket.manager import ConnectionManager


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_ws_manager(request: Request) -> ConnectionManager:
    return request.app.state.ws_manager


AppServicesDep = Annotated[AppServices, Depends(get_services)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_ws_manager)]
