from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from app.core.security import is_valid_api_key
from app.schemas.events import WSClientMessageType, WSMessage, WSServerMessageType
from app.schemas.flow import FlowStatus

websocket_router = APIRouter()
logger = logging.getLogger(__name__)


@websocket_router.websocket("/ws/flows/{flow_id}")
async def flow_websocket(websocket: WebSocket, flow_id: str, after_sequence: int = 0) -> None:
    services = websocket.app.state.services
    manager = websocket.app.state.ws_manager
    settings = websocket.app.state.settings
    supplied_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    if not is_valid_api_key(settings, supplied_key):
        await websocket.close(code=4401, reason="Invalid or missing API key")
        return
    if after_sequence < 0:
        await websocket.close(code=4400, reason="after_sequence must not be negative")
        return
    services.flows.ensure_flow(flow_id, title=f"Flow {flow_id}")

    await manager.connect(flow_id, websocket)
    await manager.send_personal(
        websocket,
        WSMessage.event(
            WSServerMessageType.CONNECTED,
            flow_id=flow_id,
            payload={"message": "connected", "flow_id": flow_id},
        ),
    )
    for entry in services.ledger.list_entries(
        flow_id,
        after_sequence=after_sequence,
    ):
        await manager.send_personal(
            websocket,
            WSMessage.event(
                WSServerMessageType.LEDGER_ENTRY,
                flow_id=flow_id,
                sequence=entry.seq,
                payload={"entry": entry.model_dump(mode="json")},
            ),
        )

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                async with asyncio.timeout(settings.websocket_idle_timeout_seconds):
                    raw_message = await websocket.receive_json()
                message = WSMessage.model_validate(raw_message)
            except TimeoutError:
                await manager.send_personal(
                    websocket,
                    WSMessage.event(
                        WSServerMessageType.ERROR,
                        flow_id=flow_id,
                        payload={"message": "WebSocket idle timeout"},
                    ),
                )
                await websocket.close(code=4408, reason="Idle timeout")
                break
            except ValidationError as exc:
                await manager.send_personal(
                    websocket,
                    WSMessage.event(
                        WSServerMessageType.ERROR,
                        flow_id=flow_id,
                        payload={"message": "invalid message", "details": exc.errors()},
                    ),
                )
                continue

            if message.type in {WSClientMessageType.PING, "ping"}:
                await manager.send_personal(
                    websocket,
                    WSMessage.event(
                        WSServerMessageType.PONG,
                        flow_id=flow_id,
                        payload={"ok": True},
                    ),
                )
                continue

            if message.type == WSClientMessageType.USER_MESSAGE:
                content = str(message.payload.get("content", "")).strip()
                if not content:
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            WSServerMessageType.ERROR,
                            flow_id=flow_id,
                            payload={"message": "payload.content is required"},
                        ),
                    )
                    continue

                services.flows.update_status(flow_id, FlowStatus.running)
                interrupted = False
                collaboration_task = asyncio.create_task(
                    services.collaboration.submit(
                        flow_id=flow_id,
                        objective=content,
                        metadata=message.payload.get("metadata") or {},
                    )
                )
                try:
                    async for event in services.orchestrator.handle_user_message(
                        flow_id=flow_id,
                        content=content,
                        metadata=message.payload.get("metadata") or {},
                    ):
                        if event.type == WSServerMessageType.INTERRUPT:
                            interrupted = True
                        await manager.broadcast(flow_id, event)
                    await collaboration_task
                except ValidationError as exc:
                    collaboration_task.cancel()
                    await asyncio.gather(collaboration_task, return_exceptions=True)
                    services.flows.update_status(flow_id, FlowStatus.failed)
                    logger.info("Flow %s rejected invalid task input", flow_id)
                    services.ledger.append(
                        flow_id,
                        event_type="flow.failed",
                        actor="runtime_orchestrator",
                        payload={"message": "任务输入格式无效"},
                    )
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            WSServerMessageType.ERROR,
                            flow_id=flow_id,
                            payload={
                                "message": "任务输入格式无效",
                                "details": exc.errors(include_url=False),
                            },
                        ),
                    )
                    continue
                except Exception as exc:
                    collaboration_task.cancel()
                    await asyncio.gather(collaboration_task, return_exceptions=True)
                    services.flows.update_status(flow_id, FlowStatus.failed)
                    logger.exception("Flow %s runtime execution failed", flow_id)
                    services.ledger.append(
                        flow_id,
                        event_type="flow.failed",
                        actor="runtime_orchestrator",
                        payload={
                            "message": "任务执行失败，请查看审计记录",
                            "error_type": type(exc).__name__,
                        },
                    )
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            WSServerMessageType.ERROR,
                            flow_id=flow_id,
                            payload={
                                "message": "任务执行失败，请查看审计记录",
                                "error_type": type(exc).__name__,
                            },
                        ),
                    )
                    continue
                services.flows.update_status(
                    flow_id,
                    FlowStatus.waiting if interrupted else FlowStatus.finished,
                )
                continue

            if message.type == WSClientMessageType.APPROVAL_RESPONSE:
                approval_id = str(message.payload.get("approval_id", "")).strip()
                if not approval_id:
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            WSServerMessageType.ERROR,
                            flow_id=flow_id,
                            payload={"message": "payload.approval_id is required"},
                        ),
                    )
                    continue

                approved = message.payload.get("approved")
                if not isinstance(approved, bool):
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            WSServerMessageType.ERROR,
                            flow_id=flow_id,
                            payload={"message": "payload.approved must be a boolean"},
                        ),
                    )
                    continue

                reason = message.payload.get("reason")
                async for event in services.orchestrator.handle_approval(
                    flow_id=flow_id,
                    approval_id=approval_id,
                    approved=approved,
                    reason=str(reason) if reason is not None else None,
                ):
                    await manager.broadcast(flow_id, event)
                services.flows.update_status(flow_id, FlowStatus.finished)
                continue

            await manager.send_personal(
                websocket,
                WSMessage.event(
                    WSServerMessageType.ERROR,
                    flow_id=flow_id,
                    payload={"message": f"unsupported message type: {message.type}"},
                ),
            )
    except WebSocketDisconnect:
        await manager.disconnect(flow_id, websocket)
