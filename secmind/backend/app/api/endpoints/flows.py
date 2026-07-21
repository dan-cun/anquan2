from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.events import WSMessage
from app.schemas.flow import (
    ApprovalRequest,
    Flow,
    FlowCreateRequest,
    FlowMessageRequest,
    FlowRunResponse,
    FlowStatus,
)
from app.services.dependencies import AppServicesDep

router = APIRouter()


@router.get("", response_model=list[Flow])
async def list_flows(services: AppServicesDep) -> list[Flow]:
    return services.flows.list_flows()


@router.post("", response_model=Flow, status_code=status.HTTP_201_CREATED)
async def create_flow(
    request: FlowCreateRequest,
    services: AppServicesDep,
) -> Flow:
    flow = services.flows.create_flow(title=request.title, initial_input=request.initial_input)
    services.ledger.append(
        flow.id,
        event_type="flow.created",
        actor="api",
        payload={"title": flow.title, "initial_input": request.initial_input},
    )
    return flow


@router.get("/{flow_id}", response_model=Flow)
async def get_flow(flow_id: str, services: AppServicesDep) -> Flow:
    flow = services.flows.get_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="flow not found")
    return flow


@router.post("/{flow_id}/messages", response_model=FlowRunResponse)
async def submit_message(
    flow_id: str,
    request: FlowMessageRequest,
    services: AppServicesDep,
) -> FlowRunResponse:
    flow = services.flows.ensure_flow(flow_id, title=f"Flow {flow_id}")
    services.flows.update_status(flow.id, FlowStatus.running)

    events: list[WSMessage] = []
    async for event in services.orchestrator.handle_user_message(
        flow_id=flow.id,
        content=request.content,
        metadata=request.metadata,
    ):
        events.append(event)

    interrupted = any(event.type == "server.interrupt" for event in events)
    final_status = FlowStatus.waiting if interrupted else FlowStatus.finished
    services.flows.update_status(flow.id, final_status)
    identity_payload = next(
        (
            event.payload
            for event in events
            if event.type == "server.status"
            and event.payload.get("stage") == "execution.identity.created"
        ),
        {},
    )
    return FlowRunResponse(
        flow_id=flow.id,
        run_id=identity_payload.get("run_id"),
        task_id=identity_payload.get("task_id"),
        events=events,
    )


@router.post("/{flow_id}/approvals", response_model=FlowRunResponse)
async def submit_approval(
    flow_id: str,
    request: ApprovalRequest,
    services: AppServicesDep,
) -> FlowRunResponse:
    flow = services.flows.ensure_flow(flow_id, title=f"Flow {flow_id}")
    events: list[WSMessage] = []
    async for event in services.orchestrator.handle_approval(
        flow_id=flow.id,
        approval_id=request.approval_id,
        approved=request.approved,
        reason=request.reason,
    ):
        events.append(event)

    services.flows.update_status(flow.id, FlowStatus.finished)
    return FlowRunResponse(flow_id=flow.id, events=events)
