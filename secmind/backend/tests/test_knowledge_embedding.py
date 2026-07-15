from __future__ import annotations

import httpx
import pytest

from knowledge.embedding import EmbeddingError, QwenEmbeddingClient


def test_qwen_embedding_client_uses_openai_compatible_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0, 1, 0]},
                    {"index": 0, "embedding": [1, 0, 0]},
                ]
            },
        )

    client = QwenEmbeddingClient(
        api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1/",
        expected_vector_size=3,
        transport=httpx.MockTransport(handler),
    )

    assert client.embed(["first", "second"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    assert captured["url"] == "https://dashscope.example/compatible-mode/v1/embeddings"
    assert captured["authorization"] == "Bearer test-key"
    assert '"model":"text-embedding-v3"' in str(captured["payload"])


def test_qwen_embedding_client_rejects_bad_responses_without_leaking_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret diagnostic", request=request)

    client = QwenEmbeddingClient(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EmbeddingError, match="HTTP 401") as caught:
        client.embed_one("query")
    assert "secret diagnostic" not in str(caught.value)


def test_qwen_embedding_client_validates_dimension_and_url() -> None:
    client = QwenEmbeddingClient(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        expected_vector_size=3,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [1, 0]}]},
            )
        ),
    )

    with pytest.raises(EmbeddingError, match="dimension"):
        client.embed_one("query")
    with pytest.raises(ValueError, match="HTTPS"):
        QwenEmbeddingClient(api_key="key", base_url="http://127.0.0.1:8000/v1")
