from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.qwen3_client import Qwen3Client, Qwen3ClientError


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeUrlopen:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> FakeHTTPResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("No fake response left")
        return FakeHTTPResponse(self.responses.pop(0))


def request_json(request: Any) -> dict[str, Any]:
    return json.loads(request.data.decode("utf-8"))


def test_qwen3_client_embeds_texts_with_openai_compatible_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_urlopen = FakeUrlopen(
        [
            {
                "model": "qwen3-embedding-4b-local",
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                ],
            }
        ]
    )
    monkeypatch.setattr("app.services.qwen3_client.urllib.request.urlopen", fake_urlopen)
    client = Qwen3Client(
        base_url="http://127.0.0.1:8010",
        api_key="local-no-auth",
        embedding_model="qwen3-embedding-4b-local",
        rerank_model="qwen3-reranker-4b-local",
        default_dimensions=1024,
    )

    vectors = client.embed_texts(["素材资产图谱", "品酒大师商品讲解"], is_query=True)

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    request = fake_urlopen.requests[0]
    assert request.full_url == "http://127.0.0.1:8010/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer local-no-auth"
    assert request_json(request) == {
        "model": "qwen3-embedding-4b-local",
        "input": ["素材资产图谱", "品酒大师商品讲解"],
        "dimensions": 1024,
        "is_query": True,
    }


def test_qwen3_client_reranks_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_urlopen = FakeUrlopen(
        [
            {
                "model": "qwen3-reranker-4b-local",
                "results": [
                    {"index": 1, "relevance_score": 0.93, "document": {"text": "AssetGraph 是素材资产大脑。"}},
                    {"index": 0, "relevance_score": 0.12, "document": {"text": "今天天气不错。"}},
                ],
            }
        ]
    )
    monkeypatch.setattr("app.services.qwen3_client.urllib.request.urlopen", fake_urlopen)
    client = Qwen3Client(
        base_url="http://127.0.0.1:8010/",
        api_key="local-no-auth",
        embedding_model="qwen3-embedding-4b-local",
        rerank_model="qwen3-reranker-4b-local",
        default_dimensions=1024,
    )

    results = client.rerank("什么是 AssetGraph？", ["今天天气不错。", "AssetGraph 是素材资产大脑。"], top_n=2)

    assert results[0]["index"] == 1
    assert results[0]["relevance_score"] == 0.93
    request = fake_urlopen.requests[0]
    assert request.full_url == "http://127.0.0.1:8010/rerank"
    assert request_json(request)["model"] == "qwen3-reranker-4b-local"
    assert request_json(request)["top_n"] == 2


def test_qwen3_client_rejects_empty_embedding_input() -> None:
    client = Qwen3Client(base_url="http://127.0.0.1:8010", api_key="local-no-auth")

    with pytest.raises(Qwen3ClientError):
        client.embed_texts([])
