def test_create_and_run_flow(client):
    create_response = client.post(
        "/api/v1/flows",
        json={"title": "Demo", "initial_input": "scan target"},
    )

    assert create_response.status_code == 201
    flow = create_response.json()
    assert flow["title"] == "Demo"

    run_response = client.post(
        f"/api/v1/flows/{flow['id']}/messages",
        json={"content": "hello backend", "metadata": {"source": "test"}},
    )

    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["run_id"]
    assert payload["task_id"]
    assert payload["run_id"] != flow["id"]
    state = client.app.state.services.runtime.state(payload["run_id"])
    assert state.flow_id == flow["id"]
    assert state.task_id == payload["task_id"]
    events = payload["events"]
    assert events[-1]["type"] == "server.done"

    verify_response = client.get(f"/api/v1/ledger/{flow['id']}/verify")
    assert verify_response.status_code == 200
    assert verify_response.json()["valid"] is True
