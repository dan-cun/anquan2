from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.model_config import (
    ModelConfigInput,
    ModelConfigResponse,
    ModelConfigUpdate,
    ModelConnectionTestResponse,
    ModelUsageResponse,
)
from app.services.dependencies import AppServicesDep
from llm.manager import ModelConfigurationError, ModelConnectionError

router = APIRouter()


@router.get("/model-config", response_model=ModelConfigResponse)
async def get_model_config(services: AppServicesDep) -> ModelConfigResponse:
    return ModelConfigResponse.model_validate(services.llm_provider.configuration())


@router.put("/model-config", response_model=ModelConfigResponse)
async def update_model_config(
    request: ModelConfigUpdate,
    services: AppServicesDep,
) -> ModelConfigResponse:
    try:
        config = await services.llm_provider.apply_configuration(
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
            api_key=request.api_key.get_secret_value() if request.api_key else None,
            test_connection=request.test_connection,
        )
    except ModelConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ModelConnectionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    return ModelConfigResponse.model_validate(config)


@router.post("/model-config/test", response_model=ModelConnectionTestResponse)
async def test_model_config(
    request: ModelConfigInput,
    services: AppServicesDep,
) -> ModelConnectionTestResponse:
    try:
        result = await services.llm_provider.test_configuration(
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
            api_key=request.api_key.get_secret_value() if request.api_key else None,
        )
    except ModelConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ModelConnectionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    return ModelConnectionTestResponse.model_validate(result)


@router.get("/model-usage", response_model=ModelUsageResponse)
async def get_model_usage(
    services: AppServicesDep,
    period: Literal["day", "month", "total"] = Query(default="month"),
) -> ModelUsageResponse:
    usage = services.runtime_ledger.model_usage(period=period)
    for conversation in usage["by_conversation"]:
        flow = services.flows.get_flow(conversation["flow_id"])
        if flow is not None:
            conversation["title"] = flow.title
    return ModelUsageResponse.model_validate(usage)
