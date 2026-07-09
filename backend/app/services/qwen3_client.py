from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class Qwen3ClientError(RuntimeError):
    pass


@dataclass(slots=True)
class Qwen3Client:
    base_url: str = "http://127.0.0.1:8010"
    api_key: str = "local-no-auth"
    embedding_model: str = "qwen3-embedding-4b-local"
    rerank_model: str = "qwen3-reranker-4b-local"
    default_dimensions: int = 1024
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def embed_texts(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
        instruction: str | None = None,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            raise Qwen3ClientError("embed_texts requires at least one text")
        payload: dict[str, Any] = {
            "model": self.embedding_model,
            "input": texts,
            "dimensions": dimensions if dimensions is not None else self.default_dimensions,
            "is_query": is_query,
        }
        if instruction:
            payload["instruction"] = instruction
        response = self._request_json("POST", "/v1/embeddings", payload)
        data = response.get("data")
        if not isinstance(data, list):
            raise Qwen3ClientError("Qwen3 embedding response missing data list")
        rows = sorted(data, key=lambda row: row.get("index", 0))
        vectors: list[list[float]] = []
        for row in rows:
            embedding = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(embedding, list):
                raise Qwen3ClientError("Qwen3 embedding response row missing embedding")
            vectors.append([float(value) for value in embedding])
        return vectors

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
        if not query.strip():
            raise Qwen3ClientError("rerank requires a non-empty query")
        if not documents:
            return []
        payload: dict[str, Any] = {
            "model": self.rerank_model,
            "query": query,
            "documents": documents,
            "return_documents": return_documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n
        if instruction:
            payload["instruction"] = instruction
        if max_length is not None:
            payload["max_length"] = max_length
        response = self._request_json("POST", "/rerank", payload)
        results = response.get("results")
        if not isinstance(results, list):
            raise Qwen3ClientError("Qwen3 rerank response missing results list")
        return [dict(row) for row in results if isinstance(row, dict)]

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise Qwen3ClientError(f"Qwen3 HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise Qwen3ClientError(f"Qwen3 request failed {path}: {exc}") from exc
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))
