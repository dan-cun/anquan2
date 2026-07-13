from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.events import WSMessage
from app.schemas.flow import FlowStatus

websocket_router = APIRouter()


@websocket_router.websocket("/ws/flows/{flow_id}")
async def flow_websocket(websocket: WebSocket, flow_id: str) -> None:
    services = websocket.app.state.services
    manager = websocket.app.state.ws_manager
    services.flows.ensure_flow(flow_id, title=f"Flow {flow_id}")

    await manager.connect(flow_id, websocket)
    await manager.send_personal(
        websocket,
        WSMessage.event(
            "server.connected",
            flow_id=flow_id,
            payload={"message": "connected", "flow_id": flow_id},
        ),
    )

    try:
        while True:
            try:
                raw_message = await websocket.receive_json()
                message = WSMessage.model_validate(raw_message)
            except ValidationError as exc:
                await manager.send_personal(
                    websocket,
                    WSMessage.event(
                        "server.error",
                        flow_id=flow_id,
                        payload={"message": "invalid message", "details": exc.errors()},
                    ),
                )
                continue

            if message.type in {"client.ping", "ping"}:
                await manager.send_personal(
                    websocket,
                    WSMessage.event("server.pong", flow_id=flow_id, payload={"ok": True}),
                )
                continue

            if message.type == "client.user_message":
                content = str(message.payload.get("content", "")).strip()
                if not content:
                    await manager.send_personal(
                        websocket,
                        WSMessage.event(
                            "server.error",
                            flow_id=flow_id,
                            payload={"message": "payload.content is required"},
                        ),
                    )
                    continue

                services.flows.update_status(flow_id, FlowStatus.running)
                interrupted = False
                async for event in services.orchestrator.handle_user_message(
                    flow_id=flow_id,
                    content=content,
                    metadata=message.payload.get("metadata") or {},
                ):
                    if event.type == "server.interrupt":
                        interrupted = True
                    await manager.broadcast(flow_id, event)
                services.flows.update_status(
                    flow_id,
                    FlowStatus.waiting if interrupted else FlowStatus.finished,
                )
                continue

            if message.type == "client.approval_response":
                approval_id = str(message.payload.get("approval_id", "")).strip()
                approved = bool(message.payload.get("approved", False))
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
                    "server.error",
                    flow_id=flow_id,
                    payload={"message": f"unsupported message type: {message.type}"},
                ),
            )
    except WebSocketDisconnect:
        await manager.disconnect(flow_id, websocket)

