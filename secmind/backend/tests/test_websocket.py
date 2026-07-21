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
        status_stages = []
        timeline = []
        for _ in range(100):
            event = websocket.receive_json()
            seen_types.append(event["type"])
            entry_type = event.get("payload", {}).get("entry", {}).get("event_type")
            stage = event.get("payload", {}).get("stage")
            timeline.append((event["type"], entry_type, stage))
            if event["type"] == "server.status":
                status_stages.append(event["payload"].get("stage"))
            if event["type"] == "server.done":
                break

        assert "server.status" in seen_types
        assert "langgraph.node.completed" in status_stages
        assert "server.ledger_entry" in seen_types
        assert seen_types[-1] == "server.done"
        runtime_queued = timeline.index(
            ("server.ledger_entry", "runtime.run.queued", None)
        )
        first_node_status = next(
            index
            for index, (event_type, _entry_type, stage) in enumerate(timeline)
            if event_type == "server.status" and stage == "langgraph.node.completed"
        )
        assert runtime_queued < first_node_status


def test_websocket_accepts_short_chinese_input_and_returns_report(client):
    with client.websocket_connect("/ws/flows/short-input-flow") as websocket:
        assert websocket.receive_json()["type"] == "server.connected"
        websocket.send_json(
            {
                "type": "client.user_message",
                "payload": {"content": "你好"},
            }
        )

        done = None
        for _ in range(100):
            event = websocket.receive_json()
            assert event["type"] != "server.error"
            if event["type"] == "server.done":
                done = event
                break

    assert done is not None
    assert done["payload"]["result"]
    assert done["payload"]["report"]["executive_summary"]


def test_websocket_approval_interrupt_roundtrip(client):
    with client.websocket_connect("/ws/flows/approval-flow") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "server.connected"

        websocket.send_json(
            {
                "type": "client.user_message",
                "payload": {"content": "please request approval before continuing"},
            }
        )

        interrupt = None
        for _ in range(100):
            event = websocket.receive_json()
            if event["type"] == "server.interrupt":
                interrupt = event
                break

        assert interrupt is not None
        approval_id = interrupt["payload"]["approval_id"]

        websocket.send_json(
            {
                "type": "client.approval_response",
                "payload": {
                    "approval_id": approval_id,
                    "approved": True,
                    "reason": "test approval",
                },
            }
        )

        seen_types = []
        done = None
        for _ in range(100):
            event = websocket.receive_json()
            seen_types.append(event["type"])
            if event["type"] == "server.done":
                done = event
                break

        assert "server.ledger_entry" in seen_types
        assert done is not None
        assert done["payload"]["approved"] is True


def test_websocket_rejects_invalid_approval_response(client):
    with client.websocket_connect("/ws/flows/invalid-approval-flow") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "server.connected"

        websocket.send_json(
            {
                "type": "client.approval_response",
                "payload": {"approved": "true"},
            }
        )

        event = websocket.receive_json()
        assert event["type"] == "server.error"
        assert event["payload"]["message"] == "payload.approval_id is required"


def test_websocket_replays_entries_after_sequence(client):
    ledger = client.app.state.services.ledger
    ledger.append("replay-flow", event_type="one", actor="test", payload={"n": 1})
    second = ledger.append("replay-flow", event_type="two", actor="test", payload={"n": 2})

    response = client.get("/api/v1/ledger/replay-flow?after_sequence=1")
    assert response.status_code == 200
    assert [entry["seq"] for entry in response.json()] == [2]

    with client.websocket_connect("/ws/flows/replay-flow?after_sequence=1") as websocket:
        connected = websocket.receive_json()
        replayed = websocket.receive_json()

    assert connected["type"] == "server.connected"
    assert replayed["type"] == "server.ledger_entry"
    assert replayed["sequence"] == second.seq
    assert replayed["payload"]["entry"]["seq"] == second.seq
