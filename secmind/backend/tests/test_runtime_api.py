import time


def test_runtime_upload_task_report_and_ledger(client):
    source = b"import subprocess\nsubprocess.Popen('echo unsafe', shell=True)\n"
    upload = client.post(
        "/api/v1/uploads",
        files={"file": ("bad.py", source)},
    )
    assert upload.status_code == 201

    task = client.post(
        "/api/v1/tasks",
        json={
            "objective": "audit uploaded python code",
            "attachments": [{"ref": upload.json()["ref"]}],
        },
    )
    assert task.status_code == 202
    identity = task.json()
    run_id = identity["run_id"]
    assert identity["flow_id"]
    assert identity["task_id"]

    status = None
    for _ in range(100):
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        status = response.json()["status"]
        if status in {"completed", "partial", "failed", "denied"}:
            break
        time.sleep(0.02)

    assert status == "completed"

    report = client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["findings"]
    assert report_payload["evidence"]
    assert report_payload["flow_id"] == identity["flow_id"]
    assert report_payload["task_id"] == identity["task_id"]
    assert report_payload["review_rounds"] == 2
    assert report_payload["review_converged"] is True

    services = client.app.state.services
    persisted_report = services.repositories.results.latest_report(run_id)
    assert persisted_report is not None
    assert persisted_report.status == "completed"
    assert services.repositories.results.list_findings(run_id)
    assert services.repositories.results.list_evidence(run_id)

    ledger = client.get(f"/api/v1/runs/{run_id}/ledger")
    assert ledger.status_code == 200
    ledger_payload = ledger.json()
    assert ledger_payload["chain_valid"] is True
    assert any(event["event_type"] == "tool.completed" for event in ledger_payload["events"])


def test_runtime_event_websocket_replays_and_streams_ordered_envelopes(client):
    task = client.post(
        "/api/v1/tasks",
        json={"objective": "summarize this authorized test input"},
    )
    assert task.status_code == 202
    run_id = task.json()["run_id"]

    events = []
    with client.websocket_connect(f"/api/v1/runs/{run_id}/events?after_sequence=0") as socket:
        for _ in range(100):
            event = socket.receive_json()
            events.append(event)
            if event["event_type"] == "report.generated":
                break

    assert events[-1]["event_type"] == "report.generated"
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert len({event["event_id"] for event in events}) == len(events)
    assert all(event["schema_version"] == "1.1" for event in events)
    assert all("context" in event for event in events)
