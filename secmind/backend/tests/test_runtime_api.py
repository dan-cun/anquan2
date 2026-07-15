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
    run_id = task.json()["run_id"]

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

    ledger = client.get(f"/api/v1/runs/{run_id}/ledger")
    assert ledger.status_code == 200
    ledger_payload = ledger.json()
    assert ledger_payload["chain_valid"] is True
    assert any(event["event_type"] == "tool.completed" for event in ledger_payload["events"])
