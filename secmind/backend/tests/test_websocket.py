def test_websocket_mock_orchestrator(client):
    with client.websocket_connect("/ws/flows/ws-flow") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "server.connected"

        websocket.send_json(
            {
                "type": "client.user_message",
                "payload": {"content": "hello from websocket"},
            }
        )

        seen_types = []
        for _ in range(20):
            event = websocket.receive_json()
            seen_types.append(event["type"])
            if event["type"] == "server.done":
                break

        assert "server.status" in seen_types
        assert "server.ledger_entry" in seen_types
        assert seen_types[-1] == "server.done"

