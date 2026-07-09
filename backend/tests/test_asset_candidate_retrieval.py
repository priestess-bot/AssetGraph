from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app
from app.services.asset_candidates import AssetRetrievalIndex, cosine_similarity


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_retrieval_index_loads_artifacts_and_returns_cosine_top_k(tmp_path: Path) -> None:
    documents_path = tmp_path / "docs.jsonl"
    embeddings_path = tmp_path / "embeddings.jsonl"
    write_jsonl(
        documents_path,
        [
            {
                "document_id": "asset:AG-IMG-1:retrieval",
                "asset_code": "AG-IMG-1",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "title": "品酒大师商品主图",
                "content": "品酒大师 商品 主图",
                "content_hash": "hash-img",
                "metadata": {"asset_type": "IMG", "maitu_category": "product_image", "usage": "商品主图"},
            },
            {
                "document_id": "asset:AG-VID-1:retrieval",
                "asset_code": "AG-VID-1",
                "display_code": "MT-VID-0001",
                "local_file_code": "MT-VID-0001",
                "title": "品酒大师商品讲解视频",
                "content": "品酒大师 商品 讲解 视频",
                "content_hash": "hash-vid",
                "metadata": {"asset_type": "VID", "maitu_category": "product_video", "usage": "商品讲解视频"},
            },
        ],
    )
    write_jsonl(
        embeddings_path,
        [
            {
                "document_id": "asset:AG-IMG-1:retrieval",
                "asset_code": "AG-IMG-1",
                "content_hash": "hash-img",
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [0.0, 1.0, 0.0],
            },
            {
                "document_id": "asset:AG-VID-1:retrieval",
                "asset_code": "AG-VID-1",
                "content_hash": "hash-vid",
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            },
        ],
    )

    index = AssetRetrievalIndex.from_jsonl_paths(documents_path, embeddings_path)
    results = index.search([1.0, 0.0, 0.0], top_k=2, filters={"asset_type": "VID"})

    assert len(index.entries) == 2
    assert results[0].asset_code == "AG-VID-1"
    assert results[0].score == 1.0
    assert results[0].document["display_code"] == "MT-VID-0001"


def test_cosine_similarity_returns_zero_for_empty_or_zero_vectors() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class FakeQwen3Client:
    embedding_model = "qwen3-embedding-4b-local"
    rerank_model = "qwen3-reranker-4b-local"

    def embed_texts(self, texts: list[str], *, is_query: bool = False, instruction: str | None = None, dimensions: int | None = None) -> list[list[float]]:
        assert texts == ["找品酒大师商品讲解视频"]
        assert is_query is True
        return [[1.0, 0.0, 0.0]]

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
        return [{"index": 0, "relevance_score": 0.98}]


def test_asset_candidates_route_embeds_query_and_returns_ranked_assets() -> None:
    index = AssetRetrievalIndex(
        entries=[
            {
                "document_id": "asset:AG-VID-1:retrieval",
                "asset_code": "AG-VID-1",
                "display_code": "MT-VID-0001",
                "local_file_code": "MT-VID-0001",
                "title": "品酒大师商品讲解视频",
                "content": "品酒大师 商品 讲解 视频",
                "content_hash": "hash-vid",
                "metadata": {"asset_type": "VID", "maitu_category": "product_video", "usage": "商品讲解视频"},
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "document_id": "asset:AG-IMG-1:retrieval",
                "asset_code": "AG-IMG-1",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "title": "品酒大师商品主图",
                "content": "品酒大师 商品 主图",
                "content_hash": "hash-img",
                "metadata": {"asset_type": "IMG", "maitu_category": "product_image", "usage": "商品主图"},
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [0.0, 1.0, 0.0],
            },
        ]
    )
    app.dependency_overrides[assets.get_asset_retrieval_index] = lambda: index
    app.dependency_overrides[assets.get_candidate_qwen3_client] = lambda: FakeQwen3Client()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/assets/candidates",
                params={"q": "找品酒大师商品讲解视频", "top_k": 1, "asset_type": "VID"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "找品酒大师商品讲解视频"
    assert body["count"] == 1
    assert body["candidates"][0]["asset_code"] == "AG-VID-1"
    assert body["candidates"][0]["score"] == 1.0
    assert body["candidates"][0]["metadata"]["maitu_category"] == "product_video"


class FakeRerankQwen3Client(FakeQwen3Client):
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
        assert top_n == 2
        assert return_documents is False
        return [{"index": 1, "relevance_score": 0.99}, {"index": 0, "relevance_score": 0.2}]


def test_asset_candidates_route_can_rerank_candidate_pool() -> None:
    index = AssetRetrievalIndex(
        entries=[
            {
                "document_id": "asset:AG-VID-1:retrieval",
                "asset_code": "AG-VID-1",
                "display_code": "MT-VID-0001",
                "local_file_code": "MT-VID-0001",
                "title": "品酒大师商品讲解视频",
                "content": "品酒大师 商品 讲解 视频",
                "content_hash": "hash-vid",
                "metadata": {"asset_type": "VID", "maitu_category": "product_video", "usage": "商品讲解视频"},
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "document_id": "asset:AG-IMG-1:retrieval",
                "asset_code": "AG-IMG-1",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "title": "品酒大师商品主图",
                "content": "品酒大师 商品 主图",
                "content_hash": "hash-img",
                "metadata": {"asset_type": "IMG", "maitu_category": "product_image", "usage": "商品主图"},
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [0.0, 1.0, 0.0],
            },
        ]
    )
    app.dependency_overrides[assets.get_asset_retrieval_index] = lambda: index
    app.dependency_overrides[assets.get_candidate_qwen3_client] = lambda: FakeRerankQwen3Client()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/assets/candidates",
                params={"q": "找品酒大师商品讲解视频", "top_k": 2, "candidate_pool_size": 2, "rerank": True},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["rerank_model"] == "qwen3-reranker-4b-local"
    assert [candidate["asset_code"] for candidate in body["candidates"]] == ["AG-IMG-1", "AG-VID-1"]
    assert body["candidates"][0]["rerank_score"] == 0.99
