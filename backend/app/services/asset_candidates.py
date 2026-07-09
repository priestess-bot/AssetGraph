from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            rows.append(value)
    return rows


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        dot += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


@dataclass(slots=True)
class AssetCandidate:
    asset_code: str
    score: float
    document: dict[str, Any]

    def to_response(self, *, rerank_score: float | None = None) -> dict[str, Any]:
        content = str(self.document.get("content") or "")
        response = {
            "asset_code": self.asset_code,
            "document_id": self.document.get("document_id"),
            "display_code": self.document.get("display_code"),
            "local_file_code": self.document.get("local_file_code"),
            "title": self.document.get("title"),
            "score": self.score,
            "metadata": self.document.get("metadata") or {},
            "content_hash": self.document.get("content_hash"),
            "content_excerpt": content[:500],
        }
        if rerank_score is not None:
            response["rerank_score"] = rerank_score
        return response


@dataclass(slots=True)
class AssetRetrievalIndex:
    entries: list[dict[str, Any]]

    @classmethod
    def from_jsonl_paths(cls, documents_path: str | Path, embeddings_path: str | Path) -> "AssetRetrievalIndex":
        resolved_documents_path = resolve_project_path(documents_path)
        resolved_embeddings_path = resolve_project_path(embeddings_path)
        documents = {str(row.get("document_id")): row for row in read_jsonl(resolved_documents_path)}
        entries: list[dict[str, Any]] = []
        for embedding in read_jsonl(resolved_embeddings_path):
            document_id = str(embedding.get("document_id") or "")
            document = documents.get(document_id)
            if document is None:
                continue
            if document.get("content_hash") != embedding.get("content_hash"):
                continue
            vector = embedding.get("vector")
            if not isinstance(vector, list):
                continue
            entry = dict(document)
            entry.update(
                {
                    "model": embedding.get("model"),
                    "dimension": embedding.get("dimension"),
                    "vector": [float(value) for value in vector],
                }
            )
            entries.append(entry)
        return cls(entries=entries)

    def search(self, query_vector: list[float], *, top_k: int, filters: dict[str, str | None] | None = None) -> list[AssetCandidate]:
        normalized_filters = {key: str(value) for key, value in (filters or {}).items() if value not in (None, "")}
        candidates: list[AssetCandidate] = []
        for entry in self.entries:
            if not self._matches_filters(entry, normalized_filters):
                continue
            vector = entry.get("vector")
            if not isinstance(vector, list):
                continue
            score = cosine_similarity(query_vector, vector)
            candidates.append(AssetCandidate(asset_code=str(entry.get("asset_code") or ""), score=score, document=entry))
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[:top_k]

    @staticmethod
    def _matches_filters(entry: dict[str, Any], filters: dict[str, str]) -> bool:
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        for key, expected in filters.items():
            actual = entry.get(key)
            if actual in (None, ""):
                actual = metadata.get(key)
            if str(actual) != expected:
                return False
        return True
