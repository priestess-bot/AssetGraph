from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import rag
from app.main import app


class FakeQwen3Client:
    embedding_model = "qwen3-embedding-4b-local"
    rerank_model = "qwen3-reranker-4b-local"

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "active_model": "none", "device": "cuda"}

    def embed_texts(self, texts: list[str], *, is_query: bool = False, instruction: str | None = None, dimensions: int | None = None) -> list[list[float]]:
        assert texts == ["素材资产图谱", "品酒大师"]
        assert is_query is True
        assert dimensions == 1024
        return [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
        instruction: str | None = None,
        max_length: int | None = None,
        return_documents: bool = True,
    ) -> list[dict[str, Any]]:
        assert query == "什么是 AssetGraph？"
        assert documents == ["今天天气不错。", "AssetGraph 是素材资产大脑。"]
        assert top_n == 2
        return [
            {"index": 1, "relevance_score": 0.93, "document": {"text": "AssetGraph 是素材资产大脑。"}},
            {"index": 0, "relevance_score": 0.12, "document": {"text": "今天天气不错。"}},
        ]


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[rag.get_qwen3_client] = lambda: FakeQwen3Client()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_qwen3_health_route(client: TestClient) -> None:
    response = client.get("/api/rag/qwen3/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "active_model": "none", "device": "cuda"}


def test_embedding_route_returns_vectors(client: TestClient) -> None:
    response = client.post(
        "/api/rag/embeddings",
        json={"texts": ["素材资产图谱", "品酒大师"], "is_query": True, "dimensions": 1024},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "qwen3-embedding-4b-local",
        "dimension": 3,
        "vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    }


def test_rerank_route_returns_ranked_results(client: TestClient) -> None:
    response = client.post(
        "/api/rag/rerank",
        json={
            "query": "什么是 AssetGraph？",
            "documents": ["今天天气不错。", "AssetGraph 是素材资产大脑。"],
            "top_n": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "qwen3-reranker-4b-local"
    assert response.json()["results"][0]["index"] == 1
    assert response.json()["results"][0]["relevance_score"] == 0.93
