import time

from llm.base import LLMProvider, LLMResponse


class FakeConfiguredProvider(LLMProvider):
    name = "qwen"

    def __init__(self, model: str) -> None:
        self.model = model

    def metadata(self):
        return {
            "name": self.name,
            "configured": True,
            "model": self.model,
            "base_url": "https://example.com/v1",
        }

    async def complete(self, messages, **kwargs):
        return LLMResponse(
            content="模型生成的安全审计摘要",
            model=self.model,
            provider=self.name,
            raw={
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                }
            },
        )


def fake_provider_factory(settings):
    return FakeConfiguredProvider(settings.llm_model)


def test_model_config_is_write_only_for_api_key(client):
    response = client.get("/api/v1/model-config")

    assert response.status_code == 200
    assert "api_key" not in response.json()
    assert response.json()["api_key_configured"] is False


def test_model_config_hot_swap_drives_runtime_and_usage(client):
    services = client.app.state.services
    services.llm_provider._factory = fake_provider_factory

    update = client.put(
        "/api/v1/model-config",
        json={
            "provider": "qwen",
            "model": "qwen-test",
            "base_url": "https://example.com/v1",
            "api_key": "secret-model-key",
        },
    )

    assert update.status_code == 200
    assert update.json()["model"] == "qwen-test"
    assert update.json()["api_key_configured"] is True
    assert "secret-model-key" not in update.text
    config_events = services.runtime_ledger.events("system-model-config")
    assert config_events[-1].event_type == "model.config.updated"
    assert "secret-model-key" not in str(config_events[-1].payload)

    upload = client.post(
        "/api/v1/uploads",
        files={"file": ("safe.py", b"print('ok')\n")},
    )
    task = client.post(
        "/api/v1/tasks",
        json={
            "objective": "audit uploaded python code",
            "attachments": [{"ref": upload.json()["ref"]}],
        },
    )
    run_id = task.json()["run_id"]
    status = "pending"
    for _ in range(100):
        status = client.get(f"/api/v1/runs/{run_id}").json()["status"]
        if status in {"completed", "partial", "failed", "denied"}:
            break
        time.sleep(0.02)

    report = client.get(f"/api/v1/runs/{run_id}/report")
    usage = client.get("/api/v1/model-usage")
    events = services.runtime_ledger.events(run_id)

    assert status == "completed"
    assert report.json()["executive_summary"] == "模型生成的安全审计摘要"
    assert [event.event_type for event in events if event.event_type.startswith("llm.")] == [
        "llm.request",
        "llm.response",
    ]
    assert usage.status_code == 200
    usage_payload = usage.json()
    assert usage_payload["period"] == "month"
    assert usage_payload["request_count"] == 1
    assert usage_payload["total_tokens"] == 18
    assert usage_payload["by_model"][0]["model"] == "qwen-test"
    assert usage_payload["by_conversation"][0]["flow_id"] == run_id
    assert usage_payload["by_conversation"][0]["total_tokens"] == 18

    assert client.get("/api/v1/model-usage?period=day").status_code == 200
    assert client.get("/api/v1/model-usage?period=total").status_code == 200
    assert client.get("/api/v1/model-usage?period=invalid").status_code == 422


def test_model_connection_test_does_not_replace_active_provider(client):
    services = client.app.state.services
    services.llm_provider._factory = fake_provider_factory
    before = client.get("/api/v1/model-config").json()

    response = client.post(
        "/api/v1/model-config/test",
        json={
            "provider": "qwen",
            "model": "qwen-candidate",
            "base_url": "https://example.com/v1",
            "api_key": "candidate-key",
        },
    )
    after = client.get("/api/v1/model-config").json()

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["model"] == "qwen-candidate"
    assert after["model"] == before["model"]
    assert after["configured"] == before["configured"]


def test_model_config_rejects_missing_key_without_replacing_provider(client):
    before = client.get("/api/v1/model-config").json()
    response = client.put(
        "/api/v1/model-config",
        json={
            "provider": "qwen",
            "model": "qwen-test",
            "base_url": "https://example.com/v1",
        },
    )
    after = client.get("/api/v1/model-config").json()

    assert response.status_code == 422
    assert after["model"] == before["model"]
    assert after["configured"] == before["configured"]
