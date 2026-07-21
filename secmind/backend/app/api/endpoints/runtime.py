from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse

from app.schemas.runtime import ApprovalResponse, RunStatus, TaskRequest
from app.services.dependencies import AppServicesDep, SettingsDep

router = APIRouter()


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload(file: Annotated[UploadFile, File(...)], settings: SettingsDep) -> dict[str, Any]:
    safe_name = Path(file.filename or "upload.bin").name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    reference = f"{uuid4()}-{safe_name}"
    destination = settings.resolved_runtime_upload_root / reference
    total = 0
    try:
        with destination.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.runtime_max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Upload exceeds configured size limit",
                    )
                stream.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"schema_version": "1.0", "ref": reference, "name": safe_name, "size_bytes": total}


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_task(task: TaskRequest, services: AppServicesDep) -> dict[str, Any]:
    identity = services.execution.submit(task)
    return {
        "schema_version": "1.0",
        **identity.model_dump(mode="json"),
        "status": RunStatus.PENDING,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, services: AppServicesDep) -> dict[str, Any]:
    try:
        return services.runtime.summary(run_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@router.get("/runs/{run_id}/report")
async def get_report(run_id: str, services: AppServicesDep) -> dict[str, Any]:
    try:
        state = services.runtime.state(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if state.report is None:
        raise HTTPException(status_code=409, detail="Report is not available yet")
    return state.report.model_dump(mode="json")


@router.get("/runs/{run_id}/ledger")
async def get_ledger(
    run_id: str,
    services: AppServicesDep,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> dict[str, Any]:
    if services.runtime.ledger.load_state(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    events = services.runtime.ledger.events(run_id, after_sequence, limit)
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "events": [event.model_dump(mode="json") for event in events],
        "chain_valid": services.runtime.ledger.verify(run_id),
    }


@router.get("/runs/{run_id}/ledger/export", response_class=FileResponse)
async def export_ledger(
    run_id: str,
    services: AppServicesDep,
    settings: SettingsDep,
) -> FileResponse:
    if services.runtime.ledger.load_state(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    destination = settings.resolved_runtime_run_root / run_id / "ledger.jsonl"
    services.runtime.ledger.export_jsonl(run_id, destination)
    return FileResponse(destination, filename=f"{run_id}-ledger.jsonl")


@router.post("/runs/{run_id}/approvals/{request_id}", status_code=status.HTTP_202_ACCEPTED)
async def resolve_approval(
    run_id: str,
    request_id: str,
    response: ApprovalResponse,
    services: AppServicesDep,
) -> dict[str, Any]:
    try:
        state = services.runtime.state(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if state.pending_approval is None or state.pending_approval.request_id != request_id:
        raise HTTPException(status_code=409, detail="Approval request is not active")
    services.runtime.submit_approval(run_id, response)
    return {"schema_version": "1.0", "run_id": run_id, "accepted": True}


@router.websocket("/runs/{run_id}/events")
async def events_socket(websocket: WebSocket, run_id: str, after_sequence: int = 0) -> None:
    services = websocket.app.state.services
    if after_sequence < 0:
        await websocket.close(code=4400, reason="after_sequence must not be negative")
        return
    if services.runtime.ledger.load_state(run_id) is None:
        await websocket.close(code=4404, reason="Run not found")
        return
    await websocket.accept()
    try:
        async for event in services.runtime_event_stream.subscribe(
            run_id,
            after_sequence=after_sequence,
        ):
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        return
